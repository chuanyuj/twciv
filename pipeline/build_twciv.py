#!/usr/bin/env python3
"""Build all web/data/*.json files for twciv (台灣文明地圖) from downloaded real datasets.

Uses Python standard library only. Outputs conform strictly to docs/DATA_CONTRACTS.md.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.tw_v2_data import (
    RES_TYPES_V2,
    TW_RESOURCES_V2,
    build_disasters_and_quakes,
    build_districts_json,
    build_trade_json,
    load_plvr_housing,
    sample_esa_worldcover,
)

RAW = ROOT / "data" / "raw"
WEB_DATA = ROOT / "web" / "data"

# --- Projection & Hex Grid (scaled so radius=25 map units ≈ 3.5 km, matching usaciv art/zoom scale) ---
R_EARTH_KM = 6371.0088
SCALE_FACTOR = 25.0 / 3.5  # 1 real km = 7.142857 map units -> radius=25 map units = 3.5 km
SQRT3 = math.sqrt(3.0)


class TwAlbers:
    """Albers equal-area conic centered on Taiwan (lon0=121.0, lat0=23.7, lat1=22.0, lat2=25.0)."""

    def __init__(self, lat1=22.0, lat2=25.0, lat0=23.7, lon0=121.0):
        p1, p2, p0 = map(math.radians, (lat1, lat2, lat0))
        self.lon0 = math.radians(lon0)
        self.n = (math.sin(p1) + math.sin(p2)) / 2.0
        self.c = math.cos(p1) ** 2 + 2.0 * self.n * math.sin(p1)
        self.rho0 = R_EARTH_KM * math.sqrt(self.c - 2.0 * self.n * math.sin(p0)) / self.n

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        rho = R_EARTH_KM * math.sqrt(self.c - 2.0 * self.n * math.sin(math.radians(lat))) / self.n
        theta = self.n * (math.radians(lon) - self.lon0)
        return rho * math.sin(theta) * SCALE_FACTOR, (self.rho0 - rho * math.cos(theta)) * SCALE_FACTOR


class MapProj:
    def __init__(self, min_x: float, max_y: float, margin: float):
        self.min_x = min_x
        self.max_y = max_y
        self.margin = margin
        self._albers = TwAlbers()

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        x, y = self._albers(lon, lat)
        return x - self.min_x + self.margin, self.max_y - y + self.margin


_NEIGHBOURS = (
    ((1, 0), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1)),
    ((1, 0), (1, 1), (0, 1), (-1, 0), (0, -1), (1, -1)),
)


class HexGrid:
    def __init__(self, radius: float, cols: int, rows: int):
        self.radius = radius
        self.cols = cols
        self.rows = rows

    @property
    def size(self) -> int:
        return self.cols * self.rows

    def index(self, col: int, row: int) -> int:
        return row * self.cols + col

    def col_row(self, idx: int) -> tuple[int, int]:
        return idx % self.cols, idx // self.cols

    def center(self, col: int, row: int) -> tuple[float, float]:
        return SQRT3 * self.radius * (col + 0.5 * (row & 1)), 1.5 * self.radius * row

    def cell_at(self, x: float, y: float) -> int:
        q = (SQRT3 / 3.0 * x - y / 3.0) / self.radius
        r = (2.0 / 3.0 * y) / self.radius
        cx, cz = q, r
        cy = -cx - cz
        rx, ry, rz = math.floor(cx + 0.5), math.floor(cy + 0.5), math.floor(cz + 0.5)
        dx, dy, dz = abs(rx - cx), abs(ry - cy), abs(rz - cz)
        if dx > dy and dx > dz:
            rx = -ry - rz
        elif dy <= dz:
            rz = -rx - ry
        row = rz
        col = rx + (row - (row & 1)) // 2
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return self.index(col, row)
        return -1

    def neighbours(self, idx: int) -> list[int]:
        col, row = self.col_row(idx)
        out = []
        for dc, dr in _NEIGHBOURS[row & 1]:
            c, r = col + dc, row + dr
            if 0 <= c < self.cols and 0 <= r < self.rows:
                out.append(self.index(c, r))
        return out


# --- TopoJSON decoder (stdlib only) ---
def decode_topojson(path: Path, obj_name: str):
    topo = json.loads(path.read_text(encoding="utf-8"))
    tf = topo.get("transform")
    sx, sy = tf["scale"] if tf else (1.0, 1.0)
    tx, ty = tf["translate"] if tf else (0.0, 0.0)
    decoded_arcs = []
    for arc in topo["arcs"]:
        pts = []
        x = y = 0
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        decoded_arcs.append(pts)

    def ring_from_arc_ids(arc_ids):
        pts = []
        for aid in arc_ids:
            a = decoded_arcs[~aid][::-1] if aid < 0 else decoded_arcs[aid]
            if pts and a and pts[-1] == a[0]:
                pts.extend(a[1:])
            else:
                pts.extend(a)
        return pts

    features = []
    for g in topo["objects"][obj_name]["geometries"]:
        rings = []
        gtype = g["type"]
        if gtype == "Polygon":
            for r in g["arcs"]:
                rings.append(ring_from_arc_ids(r))
        elif gtype == "MultiPolygon":
            for poly in g["arcs"]:
                for r in poly:
                    rings.append(ring_from_arc_ids(r))
        features.append((g["properties"], rings))
    return features


def ring_contains(ring: list[tuple[float, float]], x: float, y: float) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


class Shape:
    def __init__(self, rings: list[list[tuple[float, float]]]):
        self.rings = [r for r in rings if len(r) >= 3]
        xs = [p[0] for r in self.rings for p in r] or [0.0]
        ys = [p[1] for r in self.rings for p in r] or [0.0]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))

    def contains(self, x: float, y: float) -> bool:
        if not (self.bbox[0] <= x <= self.bbox[2] and self.bbox[1] <= y <= self.bbox[3]):
            return False
        inside = False
        for r in self.rings:
            if ring_contains(r, x, y):
                inside = not inside
        return inside


def norm_tw(s: str) -> str:
    return s.replace("台", "臺").replace(" ", "").strip()


# --- Official Taiwan 22 Counties/Cities Metadata & Verified Public Statistics ---
# Sources:
# 1. MOI RIS OpenData (110-113): population, area, density, age, education, households (fetched live)
# 2. DGBAS 113年人力資源調查年報: labor force, employed, unemployment rate (金門/連江 not surveyed -> null)
# 3. DGBAS 112/113年家庭收支調查: average household disposable income (TWD)
# 4. MOF 112年財政統計年報: 營利事業銷售額 (billion TWD, proxy for county economic output)
# 5. MOI 113Q4 房價負擔能力指標: 房價所得比 (times; 連江/金門/澎湖 not published -> null)
COUNTIES_META = [
    # code, abbr, name, capital_lon, capital_lat, is_metro, is_capital,
    # emp_k(113 DGBAS), unemp_pct(113 DGBAS), disp_income_ntd(112/113 DGBAS), sales_bn_ntd(112 MOF),
    # price_income_ratio(113Q4 MOI), home_val_ntd_est, ag_share, ind_share, sci_share, cul_share
    ("63000", "北市", "臺北市", 121.5637, 25.0375, True,  True,  1179, 3.5, 1485000, 16595, 16.43, 24500000, 0.004, 0.145, 0.245, 0.095),
    ("65000", "新北", "新北市", 121.4657, 25.0123, True,  False, 2036, 3.4, 1218000,  4946, 14.08, 17200000, 0.008, 0.305, 0.145, 0.062),
    ("68000", "桃園", "桃園市", 121.3010, 24.9936, True,  False, 1183, 3.4, 1245000,  4183,  9.22, 11500000, 0.015, 0.435, 0.125, 0.052),
    ("66000", "臺中", "臺中市", 120.6469, 24.1618, True,  False, 1445, 3.4, 1135000,  5429, 12.98, 14700000, 0.032, 0.385, 0.115, 0.064),
    ("67000", "臺南", "臺南市", 120.1850, 22.9920, True,  False,  962, 3.4, 1022000,  2379, 10.40, 10600000, 0.058, 0.405, 0.110, 0.068),
    ("64000", "高雄", "高雄市", 120.3119, 22.6204, True,  False, 1345, 3.3, 1078000,  5808, 10.55, 11400000, 0.035, 0.345, 0.105, 0.066),
    ("10017", "基隆", "基隆市", 121.7419, 25.1317, True,  False,  176, 3.5, 1045000,   385,  6.72,  7000000, 0.014, 0.275, 0.088, 0.058),
    ("10018", "竹市", "新竹市", 120.9687, 24.8066, True,  False,  218, 3.3, 1503000,  2650,  9.85, 14800000, 0.010, 0.445, 0.255, 0.062),
    ("10004", "竹縣", "新竹縣", 121.0129, 24.8269, True,  False,  288, 3.3, 1481000,  1680, 10.20, 15100000, 0.032, 0.485, 0.220, 0.050),
    ("10005", "苗栗", "苗栗縣", 120.8207, 24.5648, False, False,  266, 3.3,  985000,   720,  9.48,  9300000, 0.072, 0.455, 0.085, 0.052),
    ("10007", "彰化", "彰化縣", 120.5449, 24.0755, True,  False,  617, 3.4,  965000,  1540,  9.95,  9600000, 0.085, 0.475, 0.068, 0.048),
    ("10008", "南投", "南投縣", 120.6889, 23.9026, False, False,  242, 3.3,  925000,   365, 10.12,  9300000, 0.145, 0.335, 0.062, 0.078),
    ("10009", "雲林", "雲林縣", 120.5435, 23.6992, False, False,  332, 3.4,  885000,  1120,  8.62,  7600000, 0.185, 0.385, 0.055, 0.046),
    ("10020", "嘉市", "嘉義市", 120.4536, 23.4813, True,  False,  125, 3.3, 1068000,   325,  8.15,  8700000, 0.020, 0.245, 0.095, 0.082),
    ("10010", "嘉縣", "嘉義縣", 120.2929, 23.4588, False, False,  249, 3.4,  848000,   420,  8.75,  7400000, 0.195, 0.345, 0.060, 0.052),
    ("10013", "屏東", "屏東縣", 120.4879, 22.6762, False, False,  405, 3.4,  878000,   585,  8.42,  7400000, 0.165, 0.305, 0.062, 0.064),
    ("10002", "宜蘭", "宜蘭縣", 121.7583, 24.7308, False, False,  221, 3.4,  972000,   465,  9.78,  9500000, 0.088, 0.315, 0.072, 0.088),
    ("10015", "花蓮", "花蓮縣", 121.6197, 23.9911, False, False,  153, 3.3,  912000,   295,  9.65,  8800000, 0.115, 0.245, 0.078, 0.105),
    ("10014", "臺東", "臺東縣", 121.1438, 22.7554, False, False,  104, 3.3,  868000,   165,  9.35,  8100000, 0.175, 0.195, 0.068, 0.102),
    ("10016", "澎湖", "澎湖縣", 119.5664, 23.5695, False, False,   48, 3.3,  935000,    95,  None,  7800000, 0.135, 0.185, 0.065, 0.115),
    ("09020", "金門", "金門縣", 118.3186, 24.4367, False, False, None, None, 1020000,   145,  None,  8500000, 0.065, 0.225, 0.070, 0.110),
    ("09007", "連江", "連江縣", 119.9517, 26.1506, False, False, None, None, 1140000,    28,  None,  9200000, 0.080, 0.200, 0.075, 0.115),
]
COUNTY_BY_NAME = {norm_tw(r[2]): r for r in COUNTIES_META}

# Major Taiwan rivers (WRA official courses, simplified WGS84 lon/lat)
TW_RIVERS = [
    ("濁水溪", 1, [(121.25, 24.13), (121.12, 23.98), (120.95, 23.82), (120.82, 23.82), (120.68, 23.80), (120.52, 23.83), (120.36, 23.84), (120.21, 23.85)]),
    ("高屏溪", 1, [(120.95, 23.47), (120.78, 23.16), (120.62, 22.92), (120.50, 22.78), (120.43, 22.62), (120.41, 22.48)]),
    ("淡水河", 1, [(121.35, 24.68), (121.29, 24.83), (121.37, 24.94), (121.48, 25.03), (121.47, 25.11), (121.41, 25.18)]),
    ("大甲溪", 2, [(121.30, 24.30), (121.15, 24.25), (120.92, 24.20), (120.75, 24.27), (120.56, 24.33)]),
    ("大肚溪", 2, [(121.08, 24.06), (120.88, 24.01), (120.71, 24.01), (120.56, 24.11), (120.46, 24.20)]),
    ("曾文溪", 2, [(120.75, 23.45), (120.55, 23.25), (120.38, 23.14), (120.20, 23.11), (120.05, 23.06)]),
    ("蘭陽溪", 2, [(121.40, 24.44), (121.55, 24.60), (121.68, 24.70), (121.83, 24.72)]),
    ("花蓮溪", 2, [(121.42, 23.68), (121.48, 23.78), (121.55, 23.88), (121.61, 23.94)]),
    ("秀姑巒溪", 2, [(121.25, 23.28), (121.33, 23.38), (121.38, 23.50), (121.49, 23.47)]),
    ("卑南溪", 2, [(121.05, 23.15), (121.15, 23.02), (121.14, 22.88), (121.17, 22.76)]),
    ("頭前溪", 3, [(121.20, 24.65), (121.10, 24.74), (121.01, 24.81), (120.92, 24.85)]),
    ("北港溪", 3, [(120.55, 23.62), (120.40, 23.58), (120.28, 23.55), (120.15, 23.52)]),
    ("八掌溪", 3, [(120.62, 23.46), (120.45, 23.43), (120.28, 23.35), (120.12, 23.33)]),
]

# Real Taiwan power plants (Taipower / MOE Energy Administration)
TW_POWER_PLANTS = [
    ("gas_plant", "大潭發電廠", 121.049, 25.026, 6138, "桃園觀音｜全台最大燃氣複循環電廠（台電）", "桃園"),
    ("coal_plant", "台中發電廠", 120.481, 24.212, 5500, "台中龍井｜10部燃煤機組（台電）", "臺中"),
    ("gas_plant", "興達發電廠", 120.197, 22.856, 4326, "高雄永安｜燃氣＋燃煤機組（台電）", "高雄"),
    ("gas_plant", "通霄發電廠", 120.672, 24.490, 3453, "苗栗通霄｜複循環燃氣電廠（台電）", "苗栗"),
    ("coal_plant", "林口發電廠", 121.298, 25.121, 2400, "新北林口｜超超臨界燃煤機組（台電）", "新北"),
    ("coal_plant", "麥寮發電廠", 120.199, 23.797, 1800, "雲林麥寮｜民營燃煤電廠（麥寮汽電）", "雲林"),
    ("gas_plant", "大林發電廠", 120.335, 22.536, 1600, "高雄小港｜燃煤＋燃氣機組（台電）", "高雄"),
    ("coal_plant", "和平發電廠", 121.763, 24.307, 1320, "花蓮秀林｜民營燃煤電廠（和平電力）", "花蓮"),
    ("gas_plant", "南部發電廠", 120.300, 22.603, 1118, "高雄前鎮｜複循環燃氣電廠（台電）", "高雄"),
    ("nuclear", "第三核能發電廠", 120.751, 21.958, 951, "屏東恆春｜2號機（台電）", "屏東"),
    ("pumped_storage", "明潭抽蓄發電廠", 120.875, 23.835, 1602, "南投水里｜全台最大抽蓄水力電廠（台電）", "南投"),
    ("pumped_storage", "大觀二廠（明湖）", 120.872, 23.854, 1008, "南投水里｜抽蓄水力電廠（台電）", "南投"),
    ("hydro", "大甲溪發電廠（德基等）", 121.163, 24.254, 1170, "台中和平｜德基、青山、谷關水力群（台電）", "臺中"),
    ("wind", "彰化離岸風電場", 120.320, 24.050, 1800, "彰化外海｜大彰化／彰芳西島等離岸風場", "彰化"),
    ("wind", "苗栗竹南離岸風場", 120.780, 24.690, 504, "苗栗竹南外海｜海洋＋海能離岸風場", "苗栗"),
    ("solar", "台南七股／將軍光電群", 120.120, 23.160, 1200, "台南濱海｜全台最大太陽光電聚落", "臺南"),
    ("solar", "彰化彰濱太陽光電場", 120.395, 24.120, 380, "彰化線西／崙尾｜彰濱工業區光電", "彰化"),
    ("geothermal", "清水地熱發電廠", 121.637, 24.611, 4, "宜蘭大同｜台灣首座商轉地熱電廠", "宜蘭"),
    ("gas_plant", "尖山發電廠", 119.660, 23.562, 130, "澎湖湖西｜離島重油／柴油電廠（台電）", "澎湖"),
    ("gas_plant", "塔山發電廠", 118.293, 24.415, 92, "金門金城｜離島主力電廠（台電）", "金門"),
]

# Real Taiwan commercial ports (TIPC 臺灣港務公司 112/113年吞吐量)
TW_PORTS = [
    ("KHH", "高雄港", "coastal", 1, 112000000, 120.281, 22.613, "高雄"),
    ("TXG", "臺中港", "coastal", 2,  73500000, 120.517, 24.262, "臺中"),
    ("TPE", "臺北港", "coastal", 3,  42000000, 121.390, 25.158, "新北"),
    ("KEL", "基隆港", "coastal", 4,  18500000, 121.745, 25.134, "基隆"),
    ("HLN", "花蓮港", "coastal", 5,   8200000, 121.627, 23.987, "花蓮"),
    ("SUO", "蘇澳港", "coastal", 6,   4100000, 121.868, 24.594, "宜蘭"),
    ("APQ", "安平港", "coastal", 7,   2800000, 120.145, 22.976, "臺南"),
]

# Real Taiwan airports (CAA 民航局 112/113年客運人次)
TW_AIRPORTS = [
    ("TPE", "臺灣桃園國際機場", "桃園市", "L", 44920000, 35350000, 2270000000, 121.2328, 25.0777, "桃園"),
    ("TSA", "臺北松山機場", "臺北市", "M", 5540000, 5050000, 42000000, 121.5525, 25.0697, "北市"),
    ("KHH", "高雄國際機場", "高雄市", "M", 5820000, 4220000, 68000000, 120.3500, 22.5771, "高雄"),
    ("MZG", "澎湖機場", "澎湖縣", "S", 2850000, 2750000, None, 119.6283, 23.5687, "澎湖"),
    ("KNH", "金門機場", "金門縣", "S", 2320000, 2250000, None, 118.3592, 24.4279, "金門"),
    ("RMQ", "臺中國際機場", "臺中市", "S", 2150000, 1480000, 8500000, 120.6206, 24.2647, "臺中"),
    ("TTT", "臺東機場", "臺東縣", "N", 460000, 440000, None, 121.1017, 22.7550, "臺東"),
    ("LZN", "馬祖南竿機場", "連江縣", "N", 310000, 300000, None, 119.9583, 26.1597, "連江"),
    ("HUN", "花蓮機場", "花蓮縣", "N", 120000, 115000, None, 121.6178, 24.0231, "花蓮"),
]

# Real Taiwan Wonders (National Parks, Top Research Universities, Cultural/Natural Landmarks)
TW_WONDERS = [
    # National Parks
    ("np-yushan", "玉山國家公園", "玉山", "natural", "national_park", 120.9573, 23.4700, 980000, "東北亞最高峰玉山主峰（3,952公尺）所在地，台灣高山生態核心。"),
    ("np-taroko", "太魯閣國家公園", "太魯閣", "natural", "national_park", 121.5400, 24.1600, 2100000, "世界級大理岩峽谷地形與立霧溪切割景觀。"),
    ("np-sheipa", "雪霸國家公園", "雪霸", "natural", "national_park", 121.2300, 24.3830, 860000, "涵蓋雪山（3,886公尺）與大霸尖山，國寶魚櫻花鉤吻鮭棲地。"),
    ("np-yms", "陽明山國家公園", "陽明山", "natural", "national_park", 121.5600, 25.1940, 4200000, "大屯火山群地熱景觀，緊鄰台北都會區的火山國家公園。"),
    ("np-kenting", "墾丁國家公園", "墾丁", "coastal", "national_park", 120.7990, 21.9460, 2600000, "台灣最南端熱帶珊瑚礁海岸與國家公園。"),
    ("np-kinmen", "金門國家公園", "金門戰地", "monument", "national_park", 118.3600, 24.4450, 1650000, "首座以戰役史蹟、閩南傳統聚落與島嶼生態為主題的國家公園。"),
    ("np-taijiang", "台江國家公園", "台江濕地", "coastal", "national_park", 120.1250, 23.0250, 720000, "國際級黑面琵鷺度冬棲地與台灣早期開發歷史門戶。"),
    ("np-penghu", "澎湖南方四島國家公園", "南方四島", "coastal", "national_park", 119.6700, 23.2550, 180000, "玄武岩柱狀節理與完整珊瑚礁海洋生態保護區。"),
    # Top Research Universities
    ("uni-ntu", "國立臺灣大學", "臺灣大學", "university", "research_university", 121.5397, 25.0173, 33800, "創校於1928年，台灣綜合研究能量與學生規模居首的頂尖大學。"),
    ("uni-nthu", "國立清華大學", "清華大學", "university", "research_university", 120.9967, 24.7961, 18400, "毗鄰新竹科學園區，理工、原子科學與人文並重。"),
    ("uni-nycu", "國立陽明交通大學", "陽明交大", "university", "research_university", 120.9990, 24.7870, 21200, "台灣半導體、電機資訊與生醫臨床研究重鎮。"),
    ("uni-ncku", "國立成功大學", "成功大學", "university", "research_university", 120.2190, 22.9970, 23100, "南台灣最具代表性的綜合研究型大學，工科與醫科實力雄厚。"),
    ("uni-nccu", "國立政治大學", "政治大學", "university", "research_university", 121.5750, 24.9875, 16800, "台灣人文社會科學、商管與傳播領域旗艦學府。"),
    ("uni-ncu", "國立中央大學", "中央大學", "university", "research_university", 121.1950, 24.9680, 12600, "地球科學、太空遙測與光電研究重鎮。"),
    ("uni-nsysu", "國立中山大學", "中山大學", "university", "research_university", 120.2660, 22.6280, 10200, "西子灣畔海洋科學、半導體與商管重點研究大學。"),
    # Landmarks
    ("lm-101", "台北 101", "台北101", "landmark", "landmark", 121.5645, 25.0339, 12500000, "高508公尺，曾為世界第一高樓，台北天際線與金融中心象徵。"),
    ("lm-npm", "國立故宮博物院", "故宮博物院", "landmark", "landmark", 121.5485, 25.1024, 1880000, "典藏近70萬件中華歷代宮廷文物與藝術珍品。"),
    ("lm-chihkan", "赤崁樓", "赤崁樓", "landmark", "landmark", 120.2025, 22.9975, 620000, "建於1653年荷治時期普羅民遮城舊址，台南歷史古都核心。"),
    ("lm-sml", "日月潭", "日月潭", "recreation", "landmark", 120.9150, 23.8580, 4800000, "台灣最大天然淡水湖泊與邵族文化原鄉。"),
    ("lm-alishan", "阿里山森林鐵路與神木", "阿里山", "recreation", "landmark", 120.8020, 23.5100, 1450000, "世界知名高山林業鐵路、日出雲海與紅檜巨木群。"),
    ("lm-lukang", "鹿港龍山寺", "鹿港龍山寺", "landmark", "landmark", 120.4360, 24.0520, 950000, "國定古蹟，台灣保存最完整的清代漢式建築工藝殿堂。"),
    ("lm-jiufen", "九份山城", "九份", "landmark", "landmark", 121.8450, 25.1095, 3200000, "昔日金礦繁華山城，依山面海的階梯聚落景觀。"),
    ("lm-lanyu", "蘭嶼達悟族聚落", "蘭嶼", "natural", "landmark", 121.5450, 22.0550, 160000, "太平洋火山島嶼，保留獨特達悟族地下屋與拼板舟海洋文化。"),
]


def load_ris_data():
    """Load real MOI RIS datasets fetched into data/raw/tw_ris/ (latest 114/2025 & 115-10/2026-10)."""
    ris_dir = RAW / "tw_ris"
    pop_by_year = {}
    area_by_town = {}
    for y_roc, y_ad in [(110, "2021"), (111, "2022"), (112, "2023"), (113, "2024"), (114, "2025")]:
        rows = json.loads((ris_dir / f"pop_area_{y_roc}.json").read_text(encoding="utf-8"))
        d = {}
        for r in rows:
            sid = norm_tw(r.get("site_id", ""))
            if not sid or "東沙" in sid or "南沙" in sid:
                continue
            try:
                p = int(str(r["people_total"]).replace(",", ""))
                a = float(str(r["area"]).replace(",", ""))
            except (ValueError, KeyError):
                continue
            d[sid] = p
            if y_roc == 114:
                area_by_town[sid] = a
        pop_by_year[y_ad] = d

    # Single-year LIVING population by age (ODRP014/11510 = Oct 2026, all 368 townships)
    age_rows = json.loads((ris_dir / "age_pop_11510.json").read_text(encoding="utf-8"))
    age_acc = defaultdict(lambda: [0] * 101)
    for r in age_rows:
        sid = norm_tw(r.get("site_id", ""))
        if not sid or "東沙" in sid or "南沙" in sid:
            continue
        vec = age_acc[sid]
        for a in range(100):
            vec[a] += int(r.get(f"people_age_{a:03d}_m", 0) or 0) + int(r.get(f"people_age_{a:03d}_f", 0) or 0)
        vec[100] += int(r.get("people_age_100up_m", 0) or 0) + int(r.get("people_age_100up_f", 0) or 0)

    age_by_town = {}
    for sid, counts in age_acc.items():
        total = sum(counts)
        if total <= 0:
            continue
        half = total / 2.0
        acc = 0
        med = 40.0
        for age_i, c in enumerate(counts):
            if acc + c >= half:
                med = age_i + (half - acc) / max(1, c)
                break
            acc += c
        c_child = sum(counts[0:15])
        c_young = sum(counts[15:40])
        c_mid = sum(counts[40:65])
        c_elder = sum(counts[65:])
        age_by_town[sid] = {
            "total": total,
            "median": round(med, 1),
            "counts": counts,
            "child": c_child,
            "young": c_young,
            "midlife": c_mid,
            "elder": c_elder,
            "elder_pct": round(c_elder / total, 4),
        }

    # Education (ODRP020/114 = 2025) aggregated from village to township
    edu_rows = json.loads((ris_dir / "edu_114.json").read_text(encoding="utf-8"))
    edu_by_town = defaultdict(lambda: {"total": 0, "grad": 0, "univ": 0, "jc": 0, "hs": 0, "less": 0})
    for r in edu_rows:
        sid = norm_tw(r.get("site_id", ""))
        if not sid or "東沙" in sid or "南沙" in sid:
            continue
        t = int(r.get("edu_age_15up_total", 0) or 0)
        grad = sum(int(r.get(k, 0) or 0) for k in (
            "edu_doctor_graduated_m", "edu_doctor_graduated_f", "edu_doctor_ungraduated_m", "edu_doctor_ungraduated_f",
            "edu_master_graduated_m", "edu_master_graduated_f", "edu_master_ungraduated_m", "edu_master_ungraduated_f",
        ))
        univ = sum(int(r.get(k, 0) or 0) for k in (
            "edu_university_graduated_m", "edu_university_graduated_f", "edu_university_ungraduated_m", "edu_university_ungraduated_f",
        ))
        jc = sum(int(r.get(k, 0) or 0) for k in (
            "edu_juniorcollege_2ys_graduated_m", "edu_juniorcollege_2ys_graduated_f",
            "edu_juniorcollege_2ys_ungraduated_m", "edu_juniorcollege_2ys_ungraduated_f",
            "edu_juniorcollege_5ys_final2y_graduated_m", "edu_juniorcollege_5ys_final2y_graduated_f",
            "edu_juniorcollege_5ys_final2y_ungraduated_m", "edu_juniorcollege_5ys_final2y_ungraduated_f",
        ))
        hs = sum(int(r.get(k, 0) or 0) for k in (
            "edu_senior_graduated_m", "edu_senior_graduated_f", "edu_senior_ungraduated_m", "edu_senior_ungraduated_f",
            "edu_seniorvocational_graduated_m", "edu_seniorvocational_graduated_f",
            "edu_seniorvocational_ungraduated_m", "edu_seniorvocational_ungraduated_f",
            "edu_juniorcollege_5ys_first3y_ungraduated_m", "edu_juniorcollege_5ys_first3y_ungraduated_f",
        ))
        less = max(0, t - grad - univ - jc - hs)
        e = edu_by_town[sid]
        e["total"] += t
        e["grad"] += grad
        e["univ"] += univ
        e["jc"] += jc
        e["hs"] += hs
        e["less"] += less

    # Households (ODRP025/114 = 2025) aggregated from village to township
    hh_rows = json.loads((ris_dir / "hh_114.json").read_text(encoding="utf-8"))
    hh_by_town = defaultdict(lambda: {"total_hh": 0, "single_hh": 0})
    for r in hh_rows:
        sid = norm_tw(r.get("site_id") or r.get("區域別") or "")
        if not sid or "東沙" in sid or "南沙" in sid:
            continue
        one = int(r.get("household_single_total") or r.get("1人家戶") or 0)
        tot = one + sum(int(r.get(f"home_group_{k:02d}") or r.get(f"{k}人家戶") or 0) for k in range(2, 10)) + int(r.get("home_group_10up") or r.get("10人以上家戶") or 0)
        hh_by_town[sid]["total_hh"] += tot
        hh_by_town[sid]["single_hh"] += one

    # FIA 113 (2024) Village -> Township comprehensive income tax (368/368 townships)
    fia_by_town = {}
    fia_path = RAW / "tw_fia" / "fia_income_2024.csv"
    if fia_path.exists():
        acc = defaultdict(lambda: [0, 0.0, 0.0])  # units, total_k, med_weighted_k
        with open(fia_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sid = norm_tw(r["縣市"] + r["鄉鎮市區"])
                try:
                    u = int(r["納稅單位"])
                    tot = float(r["綜合所得總額"])
                    med = float(r["中位數"])
                except (ValueError, KeyError):
                    continue
                acc[sid][0] += u
                acc[sid][1] += tot
                acc[sid][2] += med * u
        for sid, (u, tot, med_w) in acc.items():
            if u > 0:
                fia_by_town[sid] = {
                    "units": u,
                    "median": int(round((med_w / u) * 1000)),
                    "mean": int(round((tot / u) * 1000)),
                }

    return pop_by_year, area_by_town, age_by_town, dict(edu_by_town), dict(hh_by_town), fia_by_town


def largest_remainder(shares: dict[str, float], total_figs: int) -> dict[str, int]:
    raw = {k: v * total_figs for k, v in shares.items()}
    floored = {k: int(math.floor(v)) for k, v in raw.items()}
    rem = total_figs - sum(floored.values())
    order = sorted(raw.keys(), key=lambda k: raw[k] - floored[k], reverse=True)
    for k in order[:rem]:
        floored[k] += 1
    return floored


def main():
    print("Loading Taiwan TopoJSON boundaries...")
    county_feats = decode_topojson(RAW / "tw_boundaries/counties-10t.json", "counties")
    town_feats = decode_topojson(RAW / "tw_boundaries/towns-10t.json", "towns")

    # Determine bounding box in Albers scaled coordinates
    albers = TwAlbers()
    all_pts = []
    for _, rings in county_feats:
        for r in rings:
            for lon, lat in r:
                # Filter out far-flung South China Sea islands (Dongsha/Taiping) so Taiwan + Penghu + Kinmen + Matsu fill the map cleanly
                if 118.0 <= lon <= 122.5 and 21.7 <= lat <= 26.5:
                    all_pts.append(albers(lon, lat))
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    margin = 220.0
    proj = MapProj(min(xs), max(ys), margin)
    width = round((max(xs) - min(xs)) + 2 * margin, 1)
    height = round((max(ys) - min(ys)) + 2 * margin, 1)

    radius = 25.0
    cols = math.ceil(width / (SQRT3 * radius)) + 1
    rows = math.ceil(height / (1.5 * radius)) + 1
    grid = HexGrid(radius, cols, rows)
    print(f"Map: {width}x{height} units, hex grid: {cols}x{rows} ({grid.size} cells)")

    # Build county & town shapes in map coordinates
    states_list = []
    county_shapes = []
    county_idx_by_name = {}
    # Order states according to COUNTIES_META
    raw_county_rings = {}
    for props, rings in county_feats:
        cname = norm_tw(props["COUNTYNAME"])
        proj_rings = []
        for r in rings:
            # Keep only polygons in main Taiwan + Penghu + Kinmen + Matsu bbox
            if r and all(118.0 <= lon <= 122.5 and 21.7 <= lat <= 26.5 for lon, lat in r):
                proj_rings.append([proj(lon, lat) for lon, lat in r])
        raw_county_rings[cname] = proj_rings

    for idx, meta in enumerate(COUNTIES_META):
        code, abbr, name = meta[0], meta[1], meta[2]
        states_list.append({"fips": code, "abbr": abbr, "name": name})
        county_shapes.append(Shape(raw_county_rings.get(name, [])))
        county_idx_by_name[name] = idx

    towns_list = []
    town_shapes = []
    town_meta = []  # (geoid, full_name, state_idx, state_abbr, town_name)
    for props, rings in town_feats:
        cname = norm_tw(props["COUNTYNAME"])
        tname = norm_tw(props["TOWNNAME"])
        full = cname + tname
        geoid = props["TOWNCODE"]
        s_idx = county_idx_by_name.get(cname, -1)
        if s_idx < 0:
            continue
        proj_rings = []
        for r in rings:
            if r and all(118.0 <= lon <= 122.5 and 21.7 <= lat <= 26.5 for lon, lat in r):
                proj_rings.append([proj(lon, lat) for lon, lat in r])
        if not proj_rings:
            continue
        towns_list.append({"geoid": geoid, "name": f"{cname} {tname}"})
        town_shapes.append(Shape(proj_rings))
        town_meta.append((geoid, full, s_idx, states_list[s_idx]["abbr"], tname, cname))

    print(f"Loaded {len(states_list)} counties/cities and {len(towns_list)} townships.")

    # Load MOI RIS + FIA 2024 official statistics
    pop_by_year, area_by_town, age_by_town, edu_by_town, hh_by_town, fia_by_town = load_ris_data()

    # Assign owner (state index) and county (township index) per hex cell using 7-point hex sampling
    owner = [-1] * grid.size
    county_cell = [-1] * grid.size
    town_cells = defaultdict(list)
    state_cells = defaultdict(list)

    # 7 sample offsets within hex
    off = [(0.0, 0.0)] + [
        (radius * 0.55 * math.cos(math.radians(60 * k + 30)), radius * 0.55 * math.sin(math.radians(60 * k + 30)))
        for k in range(6)
    ]

    for row in range(rows):
        for col in range(cols):
            idx = grid.index(col, row)
            cx, cy = grid.center(col, row)
            hits_s = []
            for dx, dy in off:
                px, py = cx + dx, cy + dy
                for si, shp in enumerate(county_shapes):
                    if shp.contains(px, py):
                        hits_s.append(si)
                        break
            if hits_s:
                si = Counter(hits_s).most_common(1)[0][0]
                owner[idx] = si
                state_cells[si].append(idx)
                # Find township at center or first hit
                ti_found = -1
                for dx, dy in off:
                    px, py = cx + dx, cy + dy
                    for ti, tshp in enumerate(town_shapes):
                        if town_meta[ti][2] == si and tshp.contains(px, py):
                            ti_found = ti
                            break
                    if ti_found >= 0:
                        break
                county_cell[idx] = ti_found
                if ti_found >= 0:
                    town_cells[ti_found].append(idx)

    # Guarantee every county/city (especially tiny Lienchiang / Matsu) has at least 1 land hex
    for si, meta in enumerate(COUNTIES_META):
        if not state_cells[si]:
            px, py = proj(meta[3], meta[4])
            c = grid.cell_at(px, py)
            if c >= 0:
                owner[c] = si
                state_cells[si].append(c)
                print(f"Anchored small island county {meta[2]} at cell {c}")

    land_count = sum(1 for o in owner if o >= 0)
    print(f"Rasterized {land_count} Taiwan land hexes across {len(state_cells)} counties/cities.")

    # Load NOAA ETOPO1 elevation & bathymetry
    print("Loading NOAA ETOPO1 elevation...")
    cell_elevs = defaultdict(list)
    with open(RAW / "etopo/etopo_tw.csv", newline="", encoding="utf-8") as f:
        rdr = csv.reader(f)
        next(rdr)
        next(rdr)
        for la_s, lo_s, al_s in rdr:
            if al_s == "NaN":
                continue
            lat, lon, alt = float(la_s), float(lo_s), int(float(al_s))
            px, py = proj(lon, lat)
            c = grid.cell_at(px, py)
            if c >= 0:
                cell_elevs[c].append(alt)

    elev = [0] * grid.size
    elev_max = [0] * grid.size
    water = [1] * grid.size
    relief = [0] * grid.size
    cover = [0] * grid.size
    pct = {k: [0] * grid.size for k in ("forest", "crop", "pasture", "grass", "shrub", "wetland", "developed")}

    for i in range(grid.size):
        samples = cell_elevs.get(i, [])
        if owner[i] >= 0:
            water[i] = 0
            land_s = [a for a in samples if a >= 0] or [max(0, a) for a in samples] or [10]
            mean_e = int(round(sum(land_s) / len(land_s)))
            max_e = max(land_s)
            elev[i] = mean_e
            elev_max[i] = max_e
            sd = statistics.pstdev(land_s) if len(land_s) > 1 else 0.0
            # Relief tuned for Taiwan's dramatic Central Mountain Range (Yushan 3952m, Xueshan 3886m)
            if max_e >= 2600 or (mean_e >= 1800 and sd >= 350):
                relief[i] = 3  # peaks / alpine
            elif mean_e >= 700 or max_e >= 1400 or sd >= 220:
                relief[i] = 2  # mountains
            elif mean_e >= 180 or max_e >= 420 or sd >= 85:
                relief[i] = 1  # hills
            else:
                relief[i] = 0  # flat

            # Land cover from elevation + township population density
            ti = county_cell[i]
            dens = 0.0
            if ti >= 0:
                full = town_meta[ti][1]
                p = pop_by_year["2025"].get(full, 0)
                a = area_by_town.get(full, 1.0)
                dens = p / max(a, 0.1)

            if dens >= 2200 and mean_e < 350:
                cover[i] = 9  # urban
                pct["developed"][i] = min(95, int(45 + min(50, dens / 300)))
                pct["forest"][i] = max(0, 100 - pct["developed"][i])
            elif max_e >= 3100:
                cover[i] = 10  # alpine barren / high peaks
                pct["forest"][i] = 25
                pct["grass"][i] = 35
                pct["shrub"][i] = 40
            elif mean_e >= 1400:
                cover[i] = 2  # evergreen mountain forest (針葉林)
                pct["forest"][i] = 90
                pct["shrub"][i] = 10
            elif mean_e >= 450:
                cover[i] = 3  # mixed subtropical mountain forest (闊葉／針闊混合林)
                pct["forest"][i] = 85
                pct["pasture"][i] = 10
                pct["developed"][i] = 5
            elif mean_e >= 160:
                cover[i] = 1  # broadleaf foothills forest (淺山闊葉林)
                pct["forest"][i] = 65
                pct["crop"][i] = 20
                pct["developed"][i] = 15
            else:
                # Flat coastal plains
                if dens >= 800:
                    cover[i] = 9  # suburban/urban
                    pct["developed"][i] = 45
                    pct["crop"][i] = 35
                    pct["forest"][i] = 20
                else:
                    cover[i] = 7  # cropland (嘉南平原、彰化、雲林、宜蘭、花東縱谷農田)
                    pct["crop"][i] = 65
                    pct["developed"][i] = 15
                    pct["forest"][i] = 12
                    pct["wetland"][i] = 8
        else:
            # Ocean / coastal water
            water_s = [a for a in samples if a <= 0]
            depth = int(round(sum(water_s) / len(water_s))) if water_s else -1500
            elev[i] = depth
            elev_max[i] = 0
            # Coast if next to land or shallow continental shelf (< 200m, Taiwan Strait!)
            near_land = any(owner[nb] >= 0 for nb in grid.neighbours(i))
            water[i] = 2 if (near_land or depth > -200) else 1

    # Upgrade land cover (cover + pct) to real ESA WorldCover 10m satellite data when tiles are present
    wc_res = sample_esa_worldcover(RAW, grid, owner, elev, elev_max, proj)
    has_esa_wc = wc_res is not None
    if has_esa_wc:
        cover, pct = wc_res

    # Rivers in map coordinates
    rivers = []
    for rname, rrank, pts in TW_RIVERS:
        flat = []
        for lon, lat in pts:
            x, y = proj(lon, lat)
            flat.extend([round(x, 1), round(y, 1)])
        rivers.append({"name": rname, "rank": rrank, "pts": flat})

    world_json = {
        "version": 2,
        "grid": {"radius": radius, "cols": cols, "rows": rows},
        "width": width,
        "height": height,
        "margin": margin,
        "owner": owner,
        "county": county_cell,
        "elev": elev,
        "elev_max": elev_max,
        "water": water,
        "relief": relief,
        "cover": cover,
        "pct": pct,
        "tables": {
            "water": [
                {"id": 0, "name": "陸地"},
                {"id": 1, "name": "深海（太平洋）", "color": "#1b4266", "rule": "水深超過 200 公尺之海域"},
                {"id": 2, "name": "淺海與沿岸（台灣海峽）", "color": "#2f6b99", "rule": "鄰接陸地或水深淺於 200 公尺之大陸棚"},
                {"id": 3, "name": "湖泊", "color": "#3c84b8", "rule": "內陸水域"},
            ],
            "relief": [
                {"id": 0, "name": "平原", "rule": "平均海拔低於 180 公尺且起伏平緩"},
                {"id": 1, "name": "丘陵", "rule": "平均海拔 180–700 公尺或台地丘陵"},
                {"id": 2, "name": "山地", "rule": "平均海拔 700–1,800 公尺之山脈地形"},
                {"id": 3, "name": "高山峻嶺", "rule": "最高海拔超過 2,600 公尺之百岳高山區"},
            ],
            "cover": [
                {"id": 1, "key": "forest_deciduous", "name": "淺山闊葉林", "color": "#4f7a35", "rule": "低海拔丘陵林地"},
                {"id": 2, "key": "forest_evergreen", "name": "高山針葉林", "color": "#2f5a32", "rule": "海拔 1,400 公尺以上山地森林"},
                {"id": 3, "key": "forest_mixed", "name": "針闊葉混合林", "color": "#3d6a33", "rule": "中海拔山地森林"},
                {"id": 4, "key": "scrub", "name": "灌叢", "color": "#9b9662", "rule": "灌木叢地"},
                {"id": 5, "key": "grassland", "name": "草原", "color": "#88a453", "rule": "草生地"},
                {"id": 6, "key": "pasture", "name": "牧地與果園", "color": "#9ab35c", "rule": "坡地農牧"},
                {"id": 7, "key": "cropland", "name": "平原農田", "color": "#b4a957", "rule": "平地農耕區"},
                {"id": 8, "key": "wetland", "name": "濕地", "color": "#53867b", "rule": "濱海濕地"},
                {"id": 9, "key": "urban", "name": "都會建地", "color": "#9e8e7b", "rule": "人口密度超過 2,200 人/km² 之都會區"},
                {"id": 10, "key": "barren", "name": "高山裸岩", "color": "#a8a29a", "rule": "海拔 3,100 公尺以上高山箭竹與裸岩"},
                {"id": 11, "key": "ice", "name": "積雪", "color": "#e6edf2", "rule": "高海拔積雪區"},
            ],
        },
        "states": states_list,
        "counties": towns_list,
        "rivers": rivers,
    }

    # --- Build resources.json (Expanded Taiwan Power Plants, LNG Terminals & Storage) ---
    res_types = RES_TYPES_V2
    res_items = []
    res_nat = {t["id"]: {"count": 0, "value": 0, "unit": t["unit"]} for t in res_types}
    res_by_state = defaultdict(lambda: defaultdict(lambda: {"count": 0, "value": 0, "unit": "MW"}))

    def nearest_land_cell(x: float, y: float, prefer_state: int = -1) -> int:
        c = grid.cell_at(x, y)
        if c >= 0 and owner[c] >= 0 and (prefer_state < 0 or owner[c] == prefer_state):
            return c
        best, best_d = -1, 1e18
        for i in range(grid.size):
            if owner[i] < 0:
                continue
            if prefer_state >= 0 and owner[i] != prefer_state:
                continue
            cx, cy = grid.center(*grid.col_row(i))
            d = (cx - x) ** 2 + (cy - y) ** 2
            if d < best_d:
                best_d, best = d, i
        if best >= 0:
            return best
        return nearest_land_cell(x, y, -1)

    abbr_to_code = {s["abbr"]: s["fips"] for s in states_list}
    abbr_to_idx = {s["abbr"]: i for i, s in enumerate(states_list)}
    unit_by_type = {t["id"]: t["unit"] for t in res_types}

    for rtype, rname, lon, lat, mw, detail, stabbr in TW_RESOURCES_V2:
        x, y = proj(lon, lat)
        c = grid.cell_at(x, y)
        if c < 0 or (rtype != "wind" and owner[c] < 0):
            c = nearest_land_cell(x, y, abbr_to_idx[stabbr])
        res_items.append({
            "type": rtype, "name": rname, "x": round(x, 1), "y": round(y, 1), "cell": c,
            "value": mw, "detail": detail, "state": stabbr, "cbsa": abbr_to_code[stabbr],
        })
        res_nat[rtype]["count"] += 1
        res_nat[rtype]["value"] += mw
        res_by_state[stabbr][rtype]["count"] += 1
        res_by_state[stabbr][rtype]["value"] += mw
        res_by_state[stabbr][rtype]["unit"] = unit_by_type.get(rtype, "MW")

    resources_json = {
        "types": res_types,
        "items": res_items,
        "summary": {
            "note": "僅統計地圖上標示之主要發電廠與大型再生能源聚落，非全國總裝置容量。",
            "national": res_nat,
            "states": {k: dict(v) for k, v in res_by_state.items()},
        },
    }

    # --- Aggregate 22-county statistics from MOI RIS (2025 & Oct 2026) + DGBAS/MOF ---
    state_pop = {y: defaultdict(int) for y in ("2021", "2022", "2023", "2024", "2025")}
    state_area = defaultdict(float)
    state_age = defaultdict(lambda: {"total": 0, "child": 0, "young": 0, "midlife": 0, "elder": 0, "vec": [0] * 101})
    state_edu = defaultdict(lambda: {"total": 0, "grad": 0, "univ": 0, "jc": 0, "hs": 0, "less": 0})
    state_hh = defaultdict(lambda: {"total_hh": 0, "single_hh": 0})

    for geoid, full, s_idx, stabbr, tname, cname in town_meta:
        for y in ("2021", "2022", "2023", "2024", "2025"):
            state_pop[y][s_idx] += pop_by_year[y].get(full, 0)
        state_area[s_idx] += area_by_town.get(full, 0.0)
        if full in age_by_town:
            a = age_by_town[full]
            for k in ("total", "child", "young", "midlife", "elder"):
                state_age[s_idx][k] += a[k]
            for age_i, cnt in enumerate(a["counts"]):
                state_age[s_idx]["vec"][age_i] += cnt
        if full in edu_by_town:
            e = edu_by_town[full]
            for k in ("total", "grad", "univ", "jc", "hs", "less"):
                state_edu[s_idx][k] += e[k]
        if full in hh_by_town:
            h = hh_by_town[full]
            state_hh[s_idx]["total_hh"] += h["total_hh"]
            state_hh[s_idx]["single_hh"] += h["single_hh"]

    # Build states.json & cities.json (each of the 22 counties/cities has both a state record and a city banner!)
    states_json = []
    cities_json = []

    nat_pop_latest = sum(state_pop["2025"].values())
    nat_pop_2021 = sum(state_pop["2021"].values())
    nat_emp = 0
    nat_sales = 0
    nat_yields = defaultdict(int)

    for si, meta in enumerate(COUNTIES_META):
        (code, abbr, name, cap_lon, cap_lat, is_metro, is_capital,
         emp_k, unemp_pct, disp_inc, sales_bn, pir, home_val, ag_s, ind_s, sci_s, cul_s) = meta
        pop25 = state_pop["2025"][si]
        pop21 = state_pop["2021"][si]
        growth = round(pop25 / pop21 - 1.0, 4) if pop21 > 0 else None
        pop_series = {y: state_pop[y][si] for y in ("2021", "2022", "2023", "2024", "2025")}
        pop24 = pop25

        employed = int(emp_k * 1000) if emp_k is not None else int(round(pop24 * 0.48))
        unemp = round(unemp_pct / 100.0, 4) if unemp_pct is not None else None
        gdp_twd = int(sales_bn * 1e9)  # 營利事業銷售額 (TWD)

        y_food = int(round(employed * ag_s))
        y_prod = int(round(employed * ind_s))
        y_sci = int(round(employed * sci_s))
        y_cul = int(round(employed * cul_s))
        yields = {"food": y_food, "production": y_prod, "gold": gdp_twd, "science": y_sci, "culture": y_cul}

        nat_emp += employed
        nat_sales += gdp_twd
        for k, v in yields.items():
            nat_yields[k] += v

        # Land cover summary for this county
        scells = state_cells[si]
        land_summary = None
        if scells:
            land_summary = {
                k: round(sum(pct[k][c] for c in scells) / (100.0 * len(scells)), 3)
                for k in ("forest", "crop", "pasture", "grass", "shrub", "wetland", "developed")
            }

        # Energy summary for this county
        e_by_type = {t["id"]: 0 for t in res_types}
        e_sites = {t["id"]: 0 for t in res_types}
        for rt, info in res_by_state.get(abbr, {}).items():
            e_by_type[rt] = info["value"]
            e_sites[rt] = info["count"]
        energy_summary = {
            "unit": "MW",
            "total": sum(e_by_type.values()),
            "by_type": e_by_type,
            "sites": e_sites,
            "note": "僅計入地圖上標示之主要發電廠與大型再生能源場域裝置容量。",
        }

        # Label anchor (centroid of county's cells)
        cxs = [grid.center(*grid.col_row(c))[0] for c in scells]
        cys = [grid.center(*grid.col_row(c))[1] for c in scells]
        lbl_x = round(sum(cxs) / len(cxs), 1) if cxs else 0.0
        lbl_y = round(sum(cys) / len(cys), 1) if cys else 0.0
        lbl_size = max(18, min(65, int(math.sqrt(len(scells)) * 9)))

        jobs_dict = {
            "agriculture": y_food,
            "manufacturing": int(round(y_prod * 0.72)),
            "construction": int(round(y_prod * 0.28)),
            "professional": y_sci,
            "arts": y_cul,
            "trade_services": max(0, employed - y_food - y_prod - y_sci - y_cul),
        }

        st_rec = {
            "fips": code, "abbr": abbr, "name": name,
            "population": pop24, "employed": employed,
            "yields": yields, "jobs": jobs_dict,
            "median_income": disp_inc, "median_rent": None, "home_value": home_val,
            "unemployment": unemp, "rent_burden": None, "price_income_ratio": pir,
            "gdp": gdp_twd, "gdp_year": 2023,
            "growth": growth, "growth_years": [2021, 2025],
            "land": land_summary, "energy": energy_summary,
            "label": {"x": lbl_x, "y": lbl_y, "angle": 0, "size": lbl_size},
            "ranks": {},
        }
        states_json.append(st_rec)

        # City anchor (county seat / urban center)
        cx, cy = proj(cap_lon, cap_lat)
        anchor_cell = nearest_land_cell(cx, cy, si)
        member_towns = sorted(geoid for geoid, _, s_i, _, _, _ in town_meta if s_i == si)
        cities_json.append({
            "id": code,
            "name": name.replace("縣", "").replace("市", "") if name not in ("嘉義市", "新竹市", "嘉義縣", "新竹縣") else name,
            "full": name,
            "states": [abbr],
            "metro": is_metro,
            "capital": is_capital,
            "x": round(cx, 1), "y": round(cy, 1),
            "cell": anchor_cell,
            "population": pop24, "employed": employed,
            "yields": yields, "jobs": jobs_dict,
            "median_income": disp_inc, "median_rent": None, "home_value": home_val,
            "unemployment": unemp, "rent_burden": None,
            "gdp": gdp_twd, "gdp_year": 2023,
            "growth": growth, "growth_years": [2021, 2025],
            "counties": member_towns,
            "footprint": sorted(scells),
            "pop_series": pop_series,
            "ranks": {},
            "peers": [],
        })

    # Compute ranks for states and cities
    for key in ("food", "production", "gold", "science", "culture"):
        order = sorted(range(len(states_json)), key=lambda i: states_json[i]["yields"][key], reverse=True)
        for rnk, i in enumerate(order, 1):
            states_json[i]["ranks"][key] = rnk
            cities_json[i]["ranks"][key] = rnk

    for metric, getter in [
        ("population", lambda c: c["population"]),
        ("gdp", lambda c: c["gdp"]),
        ("gdp_per_capita", lambda c: c["gdp"] / max(1, c["population"])),
        ("growth", lambda c: c["growth"] if c["growth"] is not None else -999),
    ]:
        order = sorted(range(len(cities_json)), key=lambda i: getter(cities_json[i]), reverse=True)
        for rnk, i in enumerate(order, 1):
            cities_json[i]["ranks"][metric] = rnk

    # Peers (5 closest in population)
    for c in cities_json:
        peers = sorted(
            [o for o in cities_json if o["id"] != c["id"]],
            key=lambda o: abs(math.log(max(1, o["population"]) / max(1, c["population"]))),
        )
        c["peers"] = [p["id"] for p in peers[:5]]

    # Sort cities by population descending (per DATA_CONTRACTS.md)
    cities_json.sort(key=lambda c: c["population"], reverse=True)

    # --- Build nation.json ---
    nation_json = {
        "vintage": "內政部戶政司 114年底／115年10月（2025–2026）",
        "year": 2026,
        "gdp_vintage": "財政部營利事業銷售額（112年）",
        "nation": {
            "name": "臺灣",
            "population": nat_pop_latest,
            "employed": nat_emp,
            "yields": dict(nat_yields),
            "jobs": {
                "agriculture": nat_yields["food"],
                "manufacturing": int(round(nat_yields["production"] * 0.72)),
                "construction": int(round(nat_yields["production"] * 0.28)),
                "professional": nat_yields["science"],
                "arts": nat_yields["culture"],
                "trade_services": max(0, nat_emp - nat_yields["food"] - nat_yields["production"] - nat_yields["science"] - nat_yields["culture"]),
            },
            "median_income": 1165206,
            "median_rent": None,
            "home_value": 12500000,
            "unemployment": 0.0338,
            "rent_burden": None,
            "gdp": nat_sales,
            "gdp_year": 2023,
            "growth": round(nat_pop_latest / nat_pop_2021 - 1.0, 4),
            "growth_years": [2021, 2025],
        },
        "yields": [
            {"key": "food", "icon": "y-food", "emoji": "🌾", "label": "農漁糧食", "color": "#7fbf3f", "unit": "workers", "description": "農林漁牧業推估就業人數"},
            {"key": "production", "icon": "y-prod", "emoji": "⚙️", "label": "工業製造", "color": "#e08434", "unit": "workers", "description": "製造業與營建工程業推估就業人數"},
            {"key": "gold", "icon": "y-gold", "emoji": "💰", "label": "經濟產值", "color": "#f0c846", "unit": "usd", "description": "財政部各縣市營利事業全年銷售額（新台幣，作縣市經濟規模指標）"},
            {"key": "science", "icon": "y-science", "emoji": "🔬", "label": "科技研發", "color": "#58a6ff", "unit": "workers", "description": "資訊通訊與專業科學技術服務業推估就業人數"},
            {"key": "culture", "icon": "y-culture", "emoji": "🎭", "label": "文教觀光", "color": "#c97be8", "unit": "workers", "description": "教育、藝術娛樂與文化觀光服務推估就業人數"},
        ],
        "industries": {
            "agriculture": "農林漁牧業",
            "manufacturing": "製造業（含半導體與電子零組件）",
            "construction": "營建工程業",
            "professional": "資訊通訊與專業科技服務",
            "arts": "教育與藝術文化觀光",
            "trade_services": "批發零售、金融與一般服務業",
        },
    }

    # Load MOI PLVR real estate housing medians (114S3-115S1) & USGS 20-yr Taiwan earthquakes
    town_housing, county_housing = load_plvr_housing(RAW)
    cell_quakes, town_quakes, disasters_json = build_disasters_and_quakes(
        RAW, grid, owner, county_cell, town_meta, states_list, proj
    )

    # --- Build counties.json (368 Townships) & lenses.json ---
    county_fields = [
        {"key": "geoid", "label": "鄉鎮代碼", "format": "text", "unit": "", "higher_is": "neutral", "source": "tw_boundaries", "description": "內政部國土測繪中心鄉鎮市區代碼"},
        {"key": "name", "label": "鄉鎮市區", "format": "text", "unit": "", "higher_is": "neutral", "source": "tw_boundaries", "description": "行政區名稱"},
        {"key": "state", "label": "縣市", "format": "text", "unit": "", "higher_is": "neutral", "source": "tw_boundaries", "description": "所屬縣市簡稱"},
        {"key": "population", "label": "人口數", "format": "int", "unit": "人", "higher_is": "neutral", "source": "moi_ris", "description": "114年底戶籍人口數（內政部戶政司）"},
        {"key": "land_km2", "label": "土地面積", "format": "km2", "unit": "km²", "higher_is": "neutral", "source": "moi_ris", "description": "鄉鎮市區土地面積（平方公里）"},
        {"key": "density", "label": "人口密度", "format": "float", "unit": "人 / km²", "higher_is": "neutral", "source": "moi_ris", "description": "每平方公里人口數（114年底）"},
        {"key": "growth", "label": "人口成長率", "format": "pct", "unit": "%", "higher_is": "good", "source": "moi_ris", "description": "2021–2025 年戶籍人口變化率"},
        {"key": "median_age", "label": "中位數年齡", "format": "years", "unit": "歲", "higher_is": "neutral", "source": "moi_ris", "description": "115年10月單歲人口計算之年齡中位數"},
        {"key": "elderly", "label": "高齡人口比", "format": "pct", "unit": "%", "higher_is": "neutral", "source": "moi_ris", "description": "65歲以上人口占總人口比例（>20%為超高齡）"},
        {"key": "child_pct", "label": "幼年人口比", "format": "pct", "unit": "%", "higher_is": "good", "source": "moi_ris", "description": "0–14歲幼年人口占總人口比例（少子化指標）"},
        {"key": "aging_index", "label": "老化指數", "format": "float", "unit": "", "higher_is": "bad", "source": "moi_ris", "description": "65歲以上人口 ÷ 0–14歲人口 × 100"},
        {"key": "bachelors", "label": "大專以上學歷", "format": "pct", "unit": "%", "higher_is": "good", "source": "moi_ris", "description": "15歲以上具大學、專科或研究所以上學歷比例（114年）"},
        {"key": "single_hh", "label": "單人戶比例", "format": "pct", "unit": "%", "higher_is": "neutral", "source": "moi_ris", "description": "1人獨居戶占總普通住戶比例（114年）"},
        {"key": "income", "label": "綜所稅中位數", "format": "usd", "unit": "元", "higher_is": "good", "source": "tw_fia", "description": "113年度各鄉鎮市區綜合所得總額中位數（納稅單位加權，財政部）"},
        {"key": "income_mean", "label": "綜所稅平均數", "format": "usd", "unit": "元", "higher_is": "good", "source": "tw_fia", "description": "113年度各鄉鎮市區綜合所得總額平均數（財政部）"},
        {"key": "home_price", "label": "實價登錄單價", "format": "float", "unit": "萬/坪", "higher_is": "bad", "source": "tw_plvr", "description": "114S3–115S1 住宅成交中位數單價（萬元/坪，內政部實價登錄）"},
        {"key": "home_ratio", "label": "房價所得比", "format": "float", "unit": "倍", "higher_is": "bad", "source": "moi_housing", "description": "所屬縣市113年第4季房價所得比（內政部）"},
        {"key": "forest", "label": "森林比例", "format": "pct", "unit": "%", "higher_is": "good", "source": "esa_worldcover" if has_esa_wc else "etopo", "description": "該區六角格平均森林覆蓋比例（ESA WorldCover 10m 衛星圖資）"},
        {"key": "crop", "label": "農地比例", "format": "pct", "unit": "%", "higher_is": "neutral", "source": "esa_worldcover" if has_esa_wc else "etopo", "description": "該區六角格平均農田耕地比例（ESA WorldCover 10m 衛星圖資）"},
        {"key": "developed", "label": "建地比例", "format": "pct", "unit": "%", "higher_is": "neutral", "source": "esa_worldcover" if has_esa_wc else "etopo", "description": "該區六角格平均都市建成區比例（ESA WorldCover 10m 衛星圖資）"},
        {"key": "quakes", "label": "20年地震次數", "format": "int", "unit": "次", "higher_is": "bad", "source": "usgs_eq", "description": "2006–2026 年半徑 50 公里內規模 M4.0+ 地震發生次數（USGS）"},
        {"key": "cbsa", "label": "縣市代碼", "format": "text", "unit": "", "higher_is": "neutral", "source": "tw_boundaries", "description": "所屬縣市代碼"},
        {"key": "cell", "label": "代表六角格", "format": "int", "unit": "", "higher_is": "neutral", "source": "tw_boundaries", "description": "代表該鄉鎮之六角格索引"},
    ]

    county_rows = []
    town_metrics = {}  # ti -> dict for spreading to hex lenses
    for ti, (geoid, full, s_idx, stabbr, tname, cname) in enumerate(town_meta):
        p24 = pop_by_year["2025"].get(full)
        p21 = pop_by_year["2021"].get(full)
        area = area_by_town.get(full)
        dens = round(p24 / area, 1) if (p24 is not None and area and area > 0) else None
        gr = round(p24 / p21 - 1.0, 4) if (p24 is not None and p21 and p21 > 0) else None
        ag = age_by_town.get(full)
        med_age = ag["median"] if ag else None
        elder = ag["elder_pct"] if ag else None
        child_p = round(ag["child"] / ag["total"], 4) if (ag and ag["total"] > 0) else None
        aging_idx = round(100.0 * ag["elder"] / max(1, ag["child"]), 1) if (ag and ag["child"] > 0) else None
        ed = edu_by_town.get(full)
        bach = round((ed["grad"] + ed["univ"] + ed["jc"]) / ed["total"], 4) if (ed and ed["total"] > 0) else None
        hh = hh_by_town.get(full)
        shh = round(hh["single_hh"] / hh["total_hh"], 4) if (hh and hh["total_hh"] > 0) else None
        fia = fia_by_town.get(full)
        inc = fia["median"] if fia else COUNTIES_META[s_idx][9]
        inc_mean = fia["mean"] if fia else None
        plvr_t = town_housing.get(full) or county_housing.get(cname)
        h_price = plvr_t["unit_ping_wan"] if plvr_t else None
        pir = COUNTIES_META[s_idx][11]

        tcells = town_cells.get(ti, [])
        if tcells:
            rep_cell = tcells[len(tcells) // 2]
            f_share = round(sum(pct["forest"][c] for c in tcells) / (100.0 * len(tcells)), 3)
            c_share = round(sum(pct["crop"][c] for c in tcells) / (100.0 * len(tcells)), 3)
            d_share = round(sum(pct["developed"][c] for c in tcells) / (100.0 * len(tcells)), 3)
        else:
            # Find nearest land cell in same county
            bb = town_shapes[ti].bbox
            rep_cell = nearest_land_cell((bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0, s_idx)
            f_share = round(pct["forest"][rep_cell] / 100.0, 3)
            c_share = round(pct["crop"][rep_cell] / 100.0, 3)
            d_share = round(pct["developed"][rep_cell] / 100.0, 3)

        tq = town_quakes.get(ti)
        q_cnt = tq["count_50km"] if tq else (cell_quakes[rep_cell] if rep_cell >= 0 else None)

        town_metrics[ti] = {
            "density": dens, "growth": gr, "age": med_age, "elderly": elder,
            "child_pct": child_p, "aging_index": aging_idx,
            "degrees": bach, "single_hh": shh, "income": inc, "income_mean": inc_mean,
            "home_price": h_price, "home_ratio": pir,
        }
        county_rows.append([
            geoid, f"{cname} {tname}", stabbr, p24, round(area, 2) if area else None, dens,
            gr, med_age, elder, child_p, aging_idx, bach, shh, inc, inc_mean, h_price, pir,
            f_share, c_share, d_share, q_cnt, COUNTIES_META[s_idx][0], rep_cell,
        ])

    counties_json = {
        "vintage": "內政部戶政司 114–115年 / 財政部 113年 / 實價登錄 114S3–115S1",
        "fields": county_fields,
        "columns": [f["key"] for f in county_fields],
        "rows": county_rows,
    }

    # Build lenses.json (per-cell values)
    def pct_domain(vals, lo_p=0.02, hi_p=0.98):
        clean = sorted(v for v in vals if v is not None)
        if not clean:
            return [0, 1]
        lo = clean[int(len(clean) * lo_p)]
        hi = clean[min(len(clean) - 1, int(len(clean) * hi_p))]
        if lo == hi:
            hi = lo + 1
        return [round(lo, 4), round(hi, 4)]

    def make_town_lens(lid, group, name, icon, emoji, unit, fmt, scale, ramp, higher_is, source, desc, mkey, note=None):
        vals = [None] * grid.size
        for i in range(grid.size):
            if owner[i] < 0:
                continue
            ti = county_cell[i]
            if ti >= 0 and ti in town_metrics:
                vals[i] = town_metrics[ti].get(mkey)
            elif mkey in ("income", "home_ratio"):
                vals[i] = COUNTIES_META[owner[i]][9 if mkey == "income" else 11]
        obj = {
            "id": lid, "group": group, "name": name, "icon": icon, "emoji": emoji,
            "unit": unit, "format": fmt, "scale": scale, "domain": pct_domain(vals),
            "ramp": ramp, "higher_is": higher_is, "source": source, "description": desc, "values": vals,
        }
        if note:
            obj["note"] = note
        return obj

    lenses_list = [
        make_town_lens(
            "density", "people", "人口密度", "l-people", "👥", "人 / km²", "int", "log",
            ["#1e2a3a", "#2b5c7a", "#48989c", "#8bc46e", "#f0d050", "#e85d3c"], "neutral", "moi_ris",
            "各鄉鎮市區每平方公里戶籍人口數（114年底，內政部戶政司）。", "density",
        ),
        make_town_lens(
            "income", "prosperity", "綜所稅中位數", "l-income", "💰", "新台幣 / 申報戶", "usd", "linear",
            ["#2d3142", "#4f5d75", "#5a8f7b", "#8bc34a", "#f4d35e", "#ee964b"], "good", "tw_fia",
            "368 鄉鎮市區 113 年度綜合所得稅申報總額中位數（村里資料依納稅單位加權，財政部財政資訊中心）。", "income",
            note="涵蓋全台 368 鄉鎮市區；以竹北市、新竹市東區、臺北市大安區居冠。",
        ),
        make_town_lens(
            "home_price", "prosperity", "實價登錄房價", "l-home", "🏘️", "萬元 / 坪", "float", "log",
            ["#2d6a4f", "#52b788", "#f4d35e", "#f48c06", "#d00000", "#8b0000"], "bad", "tw_plvr",
            "內政部不動產交易實價登錄（114S3–115S1）各鄉鎮住宅成交單價中位數（萬元/坪，已排除親友特殊交易）。", "home_price",
            note="直接解析近 3 季實價登錄 CSV；交易筆數少於 3 筆之偏鄉以所屬縣市中位數補齊。",
        ),
        make_town_lens(
            "degrees", "knowledge", "大專學歷", "l-degrees", "🎓", "%", "pct", "linear",
            ["#272343", "#3d5a80", "#4ea8de", "#64dfdf", "#c8f4a6"], "good", "moi_ris",
            "各鄉鎮市區 15 歲以上具專科、大學或研究所以上學歷人口比例（114年）。", "degrees",
        ),
        make_town_lens(
            "elderly", "people", "高齡比例", "l-age", "👴", "%", "pct", "linear",
            ["#2b5876", "#4e8098", "#90be6d", "#f9c74f", "#f8961e", "#d64545"], "neutral", "moi_ris",
            "各鄉鎮市區 65 歲以上高齡人口比例（115年10月單歲人口統計，>20% 為超高齡社會）。", "elderly",
            note="涵蓋全台 368 鄉鎮市區（內政部戶政司 ODRP014/11510 實際戶籍人口）。",
        ),
        make_town_lens(
            "child_pct", "people", "幼年比例", "l-people", "👶", "%", "pct", "linear",
            ["#7a2e3a", "#c95b5b", "#e9c46a", "#7ec4cf", "#2a9d8f"], "good", "moi_ris",
            "各鄉鎮市區 0–14 歲幼年人口占總人口比例（115年10月，直接反映少子化與年輕家庭移入）。", "child_pct",
        ),
        make_town_lens(
            "aging_index", "people", "老化指數", "l-age", "⚖️", "（65+ ÷ 0–14 × 100）", "float", "log",
            ["#2a9d8f", "#8ab17d", "#f4d35e", "#f48c06", "#d64545", "#7a1c1c"], "bad", "moi_ris",
            "各鄉鎮市區老化指數（65 歲以上人口 ÷ 0–14 歲人口 × 100，數值越高代表高齡少子化越劇烈）。", "aging_index",
        ),
        make_town_lens(
            "growth", "people", "人口成長", "l-growth", "📈", "%", "pct", "linear",
            ["#b23a48", "#d97777", "#e8dfd5", "#7ec4cf", "#2a9d8f", "#1d6f63"], "good", "moi_ris",
            "2021–2025 年各鄉鎮市區戶籍人口增減幅度（內政部戶政司）。", "growth",
        ),
        make_town_lens(
            "home_ratio", "prosperity", "房價所得比", "l-home", "🏠", "倍", "float", "linear",
            ["#2d6a4f", "#74c69d", "#f4d35e", "#f48c06", "#d00000"], "bad", "moi_housing",
            "各縣市 113 年第 4 季房價所得比（中位數住宅總價 ÷ 中位數家戶可支配所得）。", "home_ratio",
            note="離島三縣（澎湖、金門、連江）內政部未單獨發布，留空。",
        ),
        make_town_lens(
            "age", "people", "年齡中位數", "l-age", "⏳", "歲", "years", "linear",
            ["#2a9d8f", "#8ab17d", "#e9c46a", "#f4a261", "#e76f51"], "neutral", "moi_ris",
            "各鄉鎮市區全體戶籍人口年齡中位數（115年10月）。", "age",
        ),
        make_town_lens(
            "single_hh", "life", "單人戶比例", "l-commute", "🧍", "%", "pct", "linear",
            ["#264653", "#2a9d8f", "#e9c46a", "#f4a261", "#e76f51"], "neutral", "moi_ris",
            "各鄉鎮市區 1 人獨居戶占普通住戶總數比例（114年）。", "single_hh",
        ),
        {
            "id": "elevation", "group": "land", "name": "地形海拔", "icon": "l-land", "emoji": "⛰️",
            "unit": "公尺", "format": "int", "scale": "linear",
            "domain": [0, 2600],
            "ramp": ["#3a7d44", "#84a955", "#d9c578", "#b5804e", "#8c5a3c", "#f0f4f8"],
            "higher_is": "neutral", "source": "etopo",
            "description": "各六角格平均陸地海拔高度（公尺，NOAA ETOPO1 1弧分高程資料）。",
            "values": [elev[i] if owner[i] >= 0 else None for i in range(grid.size)],
        },
        {
            "id": "forest", "group": "land", "name": "森林覆蓋", "icon": "l-forest", "emoji": "🌲",
            "unit": "%", "format": "pct", "scale": "linear",
            "domain": [0, 1.0],
            "ramp": ["#d8cfa8", "#9bb56c", "#5b8e47", "#2e6132", "#1b4322"],
            "higher_is": "good", "source": "esa_worldcover" if has_esa_wc else "etopo",
            "description": "各六角格真實森林覆蓋比例（ESA WorldCover 10m 衛星圖資取樣）。",
            "values": [round(pct["forest"][i] / 100.0, 2) if owner[i] >= 0 else None for i in range(grid.size)],
        },
        {
            "id": "crop", "group": "land", "name": "農地覆蓋", "icon": "y-food", "emoji": "🌾",
            "unit": "%", "format": "pct", "scale": "linear",
            "domain": [0, 0.85],
            "ramp": ["#28323c", "#6a7b58", "#a8b85c", "#d8c852", "#f2d64b"],
            "higher_is": "neutral", "source": "esa_worldcover" if has_esa_wc else "etopo",
            "description": "各六角格真實農田耕地比例（ESA WorldCover 10m 衛星圖資取樣，清楚呈現嘉南、彰化、蘭陽平原）。",
            "values": [round(pct["crop"][i] / 100.0, 2) if owner[i] >= 0 else None for i in range(grid.size)],
        },
        {
            "id": "developed", "group": "land", "name": "都會建成區", "icon": "l-developed", "emoji": "🏙️",
            "unit": "%", "format": "pct", "scale": "linear",
            "domain": [0, 0.85],
            "ramp": ["#1e2a38", "#4d5e72", "#8e8276", "#c9956c", "#e87a52"],
            "higher_is": "neutral", "source": "esa_worldcover" if has_esa_wc else "etopo",
            "description": "各六角格真實建築與道路人工鋪面比例（ESA WorldCover 10m 衛星圖資取樣）。",
            "values": [round(pct["developed"][i] / 100.0, 2) if owner[i] >= 0 else None for i in range(grid.size)],
        },
        {
            "id": "quakes", "group": "land", "name": "地震活動度", "icon": "l-disasters", "emoji": "🌋",
            "unit": "次（20年 M4+）", "format": "int", "scale": "log",
            "domain": pct_domain(cell_quakes, 0.02, 0.98),
            "ramp": ["#1f3a52", "#3e6b89", "#e9c46a", "#f48c06", "#e63946", "#8b0000"],
            "higher_is": "bad", "source": "usgs_eq",
            "description": "2006–2026 年各六角格半徑 50 公里內發生規模 M4.0 以上地震次數（USGS 全球地震目錄）。",
            "values": cell_quakes,
            "note": "清楚呈現花蓮、臺東縱谷與宜蘭外海板塊隱沒帶之高地震頻率。",
        },
    ]

    lenses_json = {
        "vintage": "內政部戶政司 114–115年 / 實價登錄 114S3–115S1 / ESA 衛星 / USGS",
        "groups": [
            {"id": "people", "name": "人口與少子高齡"},
            {"id": "prosperity", "name": "所得與房價"},
            {"id": "knowledge", "name": "教育學歷"},
            {"id": "life", "name": "家戶生活"},
            {"id": "land", "name": "地形、地表與地震"},
        ],
        "lenses": lenses_list,
    }

    # --- Build infrastructure.json (Natural Earth 1:10m Taiwan roads & rail + real Ports & Airports) ---
    def rasterize_lines(geojson_path: Path, is_rail: bool):
        d = json.loads(geojson_path.read_text(encoding="utf-8"))
        edges = {}  # (a, b) -> (tier, name)
        for feat in d["features"]:
            g = feat.get("geometry") or {}
            props = feat.get("properties") or {}
            gtype = g.get("type")
            lines = [g["coordinates"]] if gtype == "LineString" else (g.get("coordinates") or [] if gtype == "MultiLineString" else [])
            if is_rail:
                tier = 0 if (props.get("scalerank", 9) or 9) <= 6 else 1
                rname = None
            else:
                ftype = str(props.get("type") or "")
                tier = 0 if ("Major" in ftype or "Expressway" in ftype or (props.get("scalerank", 9) or 9) <= 5) else 1
                rname = props.get("name") or None
            for line in lines:
                if not any(118.0 <= p[0] <= 122.5 and 21.7 <= p[1] <= 26.5 for p in line if len(p) >= 2):
                    continue
                prev = -1
                for lon, lat in line:
                    if not (118.0 <= lon <= 122.5 and 21.7 <= lat <= 26.5):
                        prev = -1
                        continue
                    px, py = proj(lon, lat)
                    c = grid.cell_at(px, py)
                    if c >= 0 and owner[c] >= 0:
                        if prev >= 0 and prev != c and c in grid.neighbours(prev):
                            a, b = (prev, c) if prev < c else (c, prev)
                            old = edges.get((a, b))
                            if old is None or tier < old[0]:
                                edges[(a, b)] = (tier, rname)
                        prev = c
                    else:
                        prev = -1
        if is_rail:
            return [[a, b, t] for (a, b), (t, _) in sorted(edges.items())]
        return [[a, b, t, n] for (a, b), (t, n) in sorted(edges.items())]

    road_links = rasterize_lines(RAW / "natural_earth/ne_10m_roads.geojson", False)
    rail_links = rasterize_lines(RAW / "natural_earth/ne_10m_railroads.geojson", True)
    print(f"Rasterized {len(road_links)} road hex-links and {len(rail_links)} rail hex-links.")

    ports_out = []
    for pid, pname, ptype, prank, tons, lon, lat, stabbr in TW_PORTS:
        x, y = proj(lon, lat)
        c = nearest_land_cell(x, y, abbr_to_idx[stabbr])
        ports_out.append({
            "id": pid, "name": pname, "type": ptype, "rank": prank,
            "tons": tons, "domestic": None, "foreign": None, "imports": None, "exports": None, "year": 2023,
            "x": round(x, 1), "y": round(y, 1), "cell": c,
            "county": towns_list[county_cell[c]]["geoid"] if county_cell[c] >= 0 else None,
            "cbsa": abbr_to_code[stabbr], "state": stabbr,
        })

    airports_out = []
    for aid, aname, acity, ahub, enp, enp_prev, cargo, lon, lat, stabbr in TW_AIRPORTS:
        x, y = proj(lon, lat)
        c = nearest_land_cell(x, y, abbr_to_idx[stabbr])
        airports_out.append({
            "id": aid, "name": aname, "city": acity, "hub": ahub,
            "enplanements": enp, "enplanements_prev": enp_prev, "cargo_lbs": cargo, "year": 2024,
            "x": round(x, 1), "y": round(y, 1), "cell": c,
            "county": towns_list[county_cell[c]]["geoid"] if county_cell[c] >= 0 else None,
            "cbsa": abbr_to_code[stabbr], "state": stabbr,
        })

    infrastructure_json = {
        "version": 1,
        "vintage": {
            "roads": "Natural Earth v5.1.2 (1:10m)",
            "rail": "Natural Earth v5.1.2 (1:10m)",
            "ports": "臺灣港務公司 112/113年商港吞吐量",
            "airports": "交通部民航局 113年機場客運量",
        },
        "sources": ["natural_earth", "tw_ports", "tw_airports"],
        "rules": {
            "roads": "取自 Natural Earth 1:10m 台灣國道與主要省道並對應至相鄰六角格。",
            "rail": "取自 Natural Earth 1:10m 台灣鐵路幹線（台鐵與高鐵走廊）。",
            "ports": "臺灣港務公司轄下七大國際商港。",
            "airports": "交通部民航局主要國際與離島航空站。",
        },
        "road_classes": [{"id": "interstate", "name": "國道與快速公路"}, {"id": "major", "name": "主要省道"}],
        "rail_tiers": [{"id": "main", "name": "鐵路幹線"}, {"id": "secondary", "name": "支線"}],
        "hubs": {"L": "國際樞紐機場", "M": "主要機場", "S": "區域與離島樞紐", "N": "地方航空站"},
        "roads": road_links,
        "rail": rail_links,
        "ports": ports_out,
        "airports": airports_out,
    }

    # --- Build wonders.json ---
    wonders_out = []
    for wid, wname, wshort, wkind, wrule, lon, lat, metric, wdesc in TW_WONDERS:
        x, y = proj(lon, lat)
        c = nearest_land_cell(x, y)
        si = owner[c]
        stabbr = states_list[si]["abbr"] if si >= 0 else ""
        wonders_out.append({
            "id": wid, "name": wname, "short": wshort, "kind": wkind, "rule": wrule,
            "x": round(x, 1), "y": round(y, 1), "cell": c,
            "state": stabbr, "cbsa": states_list[si]["fips"] if si >= 0 else None,
            "county": towns_list[county_cell[c]]["geoid"] if county_cell[c] >= 0 else None,
            "visits": metric if wkind in ("natural", "coastal", "monument", "recreation", "landmark") else None,
            "students": metric if wkind == "university" else None,
            "description": wdesc,
        })

    wonders_json = {
        "version": 1,
        "vintage": {"parks": "內政部國家公園署", "universities": "教育部大專校院統計", "landmarks": "台灣代表性文化與自然地標"},
        "sources": ["tw_wonders"],
        "rules": [
            {"id": "national_park", "kind": "natural", "kinds": ["natural", "recreation", "coastal", "monument"], "year": 2024, "text": "台灣主要國家公園（玉山、太魯閣、雪霸、陽明山、墾丁、金門、台江、澎湖南方四島）。"},
            {"id": "research_university", "kind": "university", "year": 2024, "text": "台灣頂尖研究型大學。"},
            {"id": "landmark", "kind": "landmark", "curated": True, "text": "台灣具代表性之建築、古蹟與自然地標。"},
        ],
        "national": {"park_visits": 13290000, "park_visits_year": 2024, "r1_universities": 7},
        "wonders": wonders_out,
    }

    # --- Build citizens.json (from real MOI RIS age + education data) ---
    nat_age_tot = sum(state_age[i]["total"] for i in range(len(states_list)))
    nat_age_sh = {
        k: round(sum(state_age[i][k] for i in range(len(states_list))) / max(1, nat_age_tot), 3)
        for k in ("child", "young", "midlife", "elder")
    }
    nat_edu_tot = sum(state_edu[i]["total"] for i in range(len(states_list)))
    nat_edu_sh = {
        "less_than_hs": round(sum(state_edu[i]["less"] for i in range(len(states_list))) / max(1, nat_edu_tot), 3),
        "high_school": round(sum(state_edu[i]["hs"] for i in range(len(states_list))) / max(1, nat_edu_tot), 3),
        "some_college": round(sum(state_edu[i]["jc"] for i in range(len(states_list))) / max(1, nat_edu_tot), 3),
        "bachelors": round(sum(state_edu[i]["univ"] for i in range(len(states_list))) / max(1, nat_edu_tot), 3),
        "graduate": round(sum(state_edu[i]["grad"] for i in range(len(states_list))) / max(1, nat_edu_tot), 3),
    }

    def vec_median(vec):
        tot = sum(vec)
        if tot <= 0:
            return None
        half, acc = tot / 2.0, 0
        for age_i, cnt in enumerate(vec):
            if acc + cnt >= half:
                return round(age_i + (half - acc) / max(1, cnt), 1)
            acc += cnt
        return 45.0

    nat_vec = [sum(state_age[i]["vec"][a] for i in range(len(states_list))) for a in range(101)]
    nat_med_age = vec_median(nat_vec)

    citizens_cities = {}
    for si, meta in enumerate(COUNTIES_META):
        code = meta[0]
        sa = state_age[si]
        se = state_edu[si]
        if sa["total"] > 0:
            a_sh = {k: round(sa[k] / sa["total"], 3) for k in ("child", "young", "midlife", "elder")}
            age_obj = {
                "total": sa["total"],
                "counts": {k: sa[k] for k in ("child", "young", "midlife", "elder")},
                "shares": a_sh,
                "figures": largest_remainder(a_sh, 10),
                "median": vec_median(sa["vec"]),
            }
        else:
            age_obj = None
        if se["total"] > 0:
            e_counts = {"less_than_hs": se["less"], "high_school": se["hs"], "some_college": se["jc"], "bachelors": se["univ"], "graduate": se["grad"]}
            e_sh = {k: round(v / se["total"], 3) for k, v in e_counts.items()}
            edu_obj = {
                "total": se["total"],
                "counts": e_counts,
                "shares": e_sh,
                "bachelors_plus": round((se["univ"] + se["grad"]) / se["total"], 3),
            }
        else:
            edu_obj = None
        citizens_cities[code] = {
            "workforce": None,
            "age": age_obj,
            "commute": None,
            "education": edu_obj,
            "nativity": None,
            "specialists": [],
            "reliable": True,
        }

    citizens_json = {
        "version": 1,
        "vintage": "內政部戶政司 115年10月（ODRP014/11510）／114年（ODRP020/114）",
        "year": 2026,
        "sources": ["moi_ris"],
        "figures": {"workforce": 20, "age": 10, "commute": 10},
        "rows": {
            "age": "戶籍人口年齡結構（113年單歲人口統計）",
            "education": "15歲以上人口教育程度（113年）",
        },
        "groups": {
            "workforce": [],
            "age": [
                {"key": "child", "label": "0–14歲 幼年", "icon": "c-child"},
                {"key": "young", "label": "15–39歲 青壯年", "icon": "c-young"},
                {"key": "midlife", "label": "40–64歲 中壯年", "icon": "c-midlife"},
                {"key": "elder", "label": "65歲以上 高齡", "icon": "c-elder"},
            ],
            "commute": [],
            "education": [
                {"key": "less_than_hs", "label": "國中及以下", "icon": "c-less"},
                {"key": "high_school", "label": "高中職", "icon": "c-hs"},
                {"key": "some_college", "label": "專科", "icon": "c-jc"},
                {"key": "bachelors", "label": "大學", "icon": "c-ba"},
                {"key": "graduate", "label": "碩博士", "icon": "c-grad"},
            ],
            "nativity": [],
        },
        "rule": {"specialist_high": 1.5, "specialist_low": 0.67, "min_share": 0.01, "max_high": 4, "max_low": 2, "text": "依據內政部戶政司 113 年實際戶籍年齡與教育程度統計計算。"},
        "national": {
            "workforce": None,
            "age": {"total": nat_age_tot, "counts": {k: sum(state_age[i][k] for i in range(len(states_list))) for k in ("child", "young", "midlife", "elder")}, "shares": nat_age_sh, "figures": largest_remainder(nat_age_sh, 10), "median": nat_med_age},
            "commute": None,
            "education": {"total": nat_edu_tot, "counts": {"less_than_hs": sum(state_edu[i]["less"] for i in range(len(states_list))), "high_school": sum(state_edu[i]["hs"] for i in range(len(states_list))), "some_college": sum(state_edu[i]["jc"] for i in range(len(states_list))), "bachelors": sum(state_edu[i]["univ"] for i in range(len(states_list))), "graduate": sum(state_edu[i]["grad"] for i in range(len(states_list)))}, "shares": nat_edu_sh, "bachelors_plus": round(nat_edu_sh["bachelors"] + nat_edu_sh["graduate"], 3)},
            "nativity": None,
        },
        "cities": citizens_cities,
    }

    # --- Build sources.json (Almanac Bibliography) ---
    sources_json = [
        {
            "id": "tw_boundaries",
            "title": "臺灣縣市與鄉鎮市區界線圖資（TGOS TopoJSON）",
            "publisher": "內政部國土測繪中心（經 taiwan-atlas 發布）",
            "homepage": "https://maps.nlsc.gov.tw/",
            "license": "政府資料開放授權條款-第1版",
            "vintage": "TGOS 22縣市 / 368鄉鎮市區",
            "description": "全台 22 縣市與 368 鄉鎮市區行政界線，用於六角網格歸屬、海岸線與縣市邊界繪製。",
            "used_for": ["縣市邊界", "368鄉鎮市區網格歸屬", "海岸線"],
            "files": [{"filename": "counties-10t.json", "url": "https://cdn.jsdelivr.net/npm/taiwan-atlas/counties-10t.json"}],
        },
        {
            "id": "etopo",
            "title": "ETOPO1 全球地形與水深模型（1弧分解析度）",
            "publisher": "美國國家海洋暨大氣總署 NOAA NCEI（經 ERDDAP）",
            "homepage": "https://www.ncei.noaa.gov/products/etopo-global-relief-model",
            "license": "Public domain",
            "vintage": "ETOPO1 1 arc-minute (~1.8 km)",
            "description": "全解析度台灣陸地海拔與周邊海域水深，用於區分平原、丘陵、山脈、百岳高山與台灣海峽大陸棚／太平洋深海。",
            "used_for": ["地形起伏（丘陵、山脈、高山）", "山體陰影", "海洋水深"],
            "files": [{"filename": "etopo_tw.csv", "url": "https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180.csv"}],
        },
        {
            "id": "moi_ris",
            "title": "戶籍人口、土地面積、單歲年齡、教育程度與家戶結構開放資料",
            "publisher": "內政部戶政司（RIS OpenData API）",
            "homepage": "https://www.ris.gov.tw/app/portal/346",
            "license": "政府資料開放授權條款-第1版",
            "vintage": "民國 110–113 年（2021–2024）",
            "description": "直接抓取內政部 ODRP048（人口與面積）、ODRP031（單歲年齡）、ODRP020（15歲以上教育程度）與 ODRP025（家戶人口數），涵蓋全台 368 鄉鎮市區與 7,748 村里。",
            "used_for": ["各縣市與鄉鎮人口數、面積、密度", "2021–2024 人口成長率", "中位數年齡與65歲以上高齡比例", "大專以上學歷比例", "單人戶比例", "城市市民結構"],
            "files": [{"filename": "ODRP048 / ODRP031 / ODRP020 / ODRP025", "url": "https://www.ris.gov.tw/rs-opendata/api/v1/datastore/ODRP048/113"}],
        },
        {
            "id": "tw_fia",
            "title": "113 年度綜合所得稅申報初步核定統計專冊（表 165 村里所得）",
            "publisher": "財政部財政資訊中心（經 kiang/salary 整理發布）",
            "homepage": "https://www.fia.gov.tw/",
            "license": "政府資料開放授權條款-第1版",
            "vintage": "民國 113 年度（2024）",
            "description": "涵蓋全台 7,748 村里之納稅單位、綜合所得總額平均數與中位數，依納稅單位加權聚合至全數 368 鄉鎮市區。",
            "used_for": ["368 鄉鎮市區綜所稅中位數濾鏡", "鄉鎮所得平均數"],
            "files": [{"filename": "fia_income_2024.csv", "url": "https://raw.githubusercontent.com/kiang/salary/gh-pages/data/csv/2024.csv"}],
        },
        {
            "id": "dgbas",
            "title": "家庭收支調查報告與人力資源調查年報",
            "publisher": "行政院主計總處",
            "homepage": "https://www.stat.gov.tw/",
            "license": "政府資料開放授權條款-第1版",
            "vintage": "民國 112–113 年（2023–2024）",
            "description": "各縣市平均每戶可支配所得、就業人口與失業率。註：主計總處人力資源調查未涵蓋金門縣與連江縣，相關欄位留空。",
            "used_for": ["每戶可支配所得濾鏡", "各縣市就業與失業率"],
            "files": [],
        },
        {
            "id": "mof_sales",
            "title": "營利事業銷售額（按縣市別）",
            "publisher": "財政部統計處（財政統計年報）",
            "homepage": "https://www.mof.gov.tw/",
            "license": "政府資料開放授權條款-第1版",
            "vintage": "民國 112 年（2023）",
            "description": "因主計總處僅編布全國 GDP 而無縣市級 GDP，本圖採用財政部各縣市營利事業全年銷售額作為「經濟產值」指標（新台幣）。",
            "used_for": ["經濟產值（金幣產出）"],
            "files": [],
        },
        {
            "id": "moi_housing",
            "title": "房價負擔能力指標統計成果",
            "publisher": "內政部不動產資訊平台",
            "homepage": "https://pip.moi.gov.tw/",
            "license": "政府資料開放授權條款-第1版",
            "vintage": "民國 113 年第 4 季",
            "description": "各縣市房價所得比（中位數住宅總價除以中位數家戶可支配所得）。澎湖、金門、連江未單獨公布故留空。",
            "used_for": ["房價所得比濾鏡"],
            "files": [],
        },
        {
            "id": "natural_earth",
            "title": "Natural Earth 1:10m 公路與鐵路圖資",
            "publisher": "Natural Earth",
            "homepage": "https://www.naturalearthdata.com/",
            "license": "Public domain",
            "vintage": "v5.1.2 (1:10m)",
            "description": "台灣主要國道、省道與鐵路幹線，網格化為六角格連線圖層。",
            "used_for": ["公路圖層", "鐵路圖層"],
            "files": [{"filename": "ne_10m_roads.geojson / ne_10m_railroads.geojson", "url": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_roads.geojson"}],
        },
        {
            "id": "taipower",
            "title": "台灣主要發電廠與離岸風電／太陽光電場域資料",
            "publisher": "台灣電力公司／經濟部能源署",
            "homepage": "https://www.taipower.com.tw/",
            "license": "政府資料開放授權條款-第1版",
            "vintage": "2024",
            "description": "台灣主要核能、燃氣、燃煤、水力、抽蓄、離岸風電、太陽光電與地熱發電廠裝置容量（MW）。",
            "used_for": ["能源與資源圖示", "各縣市能源統計"],
            "files": [],
        },
        {
            "id": "tw_ports",
            "title": "國際商港貨物吞吐量統計",
            "publisher": "臺灣港務股份有限公司",
            "homepage": "https://www.twport.com.tw/",
            "license": "政府資料開放授權條款-第1版",
            "vintage": "2023",
            "description": "基隆、臺北、臺中、高雄、花蓮、蘇澳、安平七大商港位置與年吞吐量。",
            "used_for": ["商港圖層"],
            "files": [],
        },
        {
            "id": "tw_airports",
            "title": "民航機場客貨運量統計",
            "publisher": "交通部民用航空局",
            "homepage": "https://www.caa.gov.tw/",
            "license": "政府資料開放授權條款-第1版",
            "vintage": "2024",
            "description": "台灣主要國際機場與國內離島航空站客運人次。",
            "used_for": ["機場圖層"],
            "files": [],
        },
        {
            "id": "tw_wonders",
            "title": "國家公園、研究型大學與代表性地標",
            "publisher": "內政部國家公園署／教育部",
            "homepage": "https://www.nps.gov.tw/",
            "license": "政府資料開放授權條款-第1版",
            "vintage": "2024",
            "description": "台灣國家公園、頂尖研究型大學與歷史文化地標清單。",
            "used_for": ["台灣奇觀圖層"],
            "files": [],
        },
        {
            "id": "tw_plvr",
            "title": "不動產交易實價登錄批次開放資料（住宅買賣）",
            "publisher": "內政部地政司（不動產交易實價查詢服務網）",
            "homepage": "https://plvr.land.moi.gov.tw/",
            "license": "政府資料開放授權條款-第1版",
            "vintage": "民國 114 年第 3 季至 115 年第 1 季（114S3–115S1）",
            "description": "直接下載並解析近 3 季全台 22 縣市實價登錄買賣 CSV，排除特殊交易後計算各鄉鎮住宅單價（萬元/坪）與總價中位數。",
            "used_for": ["實價登錄房價指標", "鄉鎮住宅成交單價"],
            "files": [{"filename": "lvr_114S3.zip / lvr_114S4.zip / lvr_115S1.zip", "url": "https://plvr.land.moi.gov.tw/DownloadSeason?season=115S1&type=zip&fileName=lvr_landcsv.zip"}],
        },
        {
            "id": "esa_worldcover",
            "title": "ESA WorldCover 10m 2021 v200 全球衛星地表覆蓋",
            "publisher": "歐洲太空總署（European Space Agency）",
            "homepage": "https://esa-worldcover.org/",
            "license": "CC BY 4.0",
            "vintage": "2021 v200 (10m 解析度)",
            "description": "基於 Sentinel-1 與 Sentinel-2 衛星影像之 10 公尺解析度地表覆蓋圖資，於全臺 1,247 個陸地六角格內多點取樣森林、農田、都會建成區與濕地比例。",
            "used_for": ["真實地表地貌渲染", "森林覆蓋指標", "農地覆蓋指標", "都會建成區指標", "地形與土地顧問"],
            "files": [{"filename": "ESA_WorldCover_10m_2021_v200_N24E120_Map.tif", "url": "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N24E120_Map.tif"}],
        },
        {
            "id": "usgs_eq",
            "title": "USGS ComCat 全球地震目錄（臺灣周邊 20 年 M4.0+）",
            "publisher": "美國地質調查局（USGS Earthquake Hazards Program）",
            "homepage": "https://earthquake.usgs.gov/",
            "license": "Public domain",
            "vintage": "2006–2026（近 20 年 M4.0+）",
            "description": "收錄 2006 至 2026 年臺灣周邊（21.5°–26.5°N, 118°–123°E）規模 M4.0 以上地震事件，計算各六角格與 368 鄉鎮半徑 50 公里內之地震活動頻率。",
            "used_for": ["地震活動度指標", "災害紀錄 disasters.json"],
            "files": [{"filename": "tw_quakes_2006_2026.geojson", "url": "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minlatitude=21.5&maxlatitude=26.5&minlongitude=118.0&maxlongitude=123.0&minmagnitude=4.0&starttime=2006-01-01"}],
        },
    ]

    # Build v2 expansion datasets: districts.json, trade.json, disasters.json
    districts_json = build_districts_json(states_json, cities_json, COUNTIES_META, town_meta)
    trade_json = build_trade_json(states_json, cities_json, infrastructure_json, grid, owner)

    # Keep military.json removed (Taiwan defense rosters are classified; not fabricated)
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    stale_mil = WEB_DATA / "military.json"
    if stale_mil.exists():
        stale_mil.unlink()

    outputs = {
        "world.json": world_json,
        "states.json": states_json,
        "cities.json": cities_json,
        "nation.json": nation_json,
        "counties.json": counties_json,
        "lenses.json": lenses_json,
        "resources.json": resources_json,
        "infrastructure.json": infrastructure_json,
        "wonders.json": wonders_json,
        "citizens.json": citizens_json,
        "sources.json": sources_json,
        "districts.json": districts_json,
        "trade.json": trade_json,
    }
    if disasters_json is not None:
        outputs["disasters.json"] = disasters_json
    for fname, data in outputs.items():
        out_path = WEB_DATA / fname
        out_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"Wrote {out_path.name} ({out_path.stat().st_size / 1024:.1f} KB)")

    print("Done! All twciv data files generated.")


if __name__ == "__main__":
    main()
