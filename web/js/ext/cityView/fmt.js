// Number formatting for the City View: delegates to format.js (NT$, 萬/億/兆).
import { compact as baseCompact, money as baseMoney, popShort as basePopShort, yieldValue as baseYieldValue } from "../../format.js";

export const compact = baseCompact;
export const money = baseMoney;
export const yieldValue = baseYieldValue;
export const popShort = basePopShort;
