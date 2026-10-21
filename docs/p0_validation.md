# P0 Validation Summary

## Result

P0 metadata preparation and validation pass.

- Stations: 1,885
- Charger configurations: 1,958
- DC configurations: 433
- Unique station IDs: 1,885
- Unique charger IDs: 1,958
- Charger-to-station foreign keys: all valid
- Station coordinates: 1,885 valid
- Stations with verified A1 connector-type evidence: 214
- Station-level connector-type rows: 344

## Operator normalization

The original label is retained beside the standardized label. A total of 170 charger configurations changed label:

| Original | Standard | Rows |
|---|---|---:|
| BP Australia | BP | 28 |
| Tesla Motors | Tesla | 27 |
| Evie | Evie Networks | 84 |
| Charge Hub | ChargeHub | 7 |
| NRMA Electric | NRMA | 15 |
| PLUS ES Manag | PLUS ES | 2 |
| Viva Energy A | Viva Energy Australia | 7 |

## Names and power

There are 509 A1 station names. The remaining 1,376 stations receive deterministic fallback names and are explicitly marked `a2_deterministic_fallback`.

Effective power is available for 1,936 charger configurations. Twenty-two unitless ratings remain unresolved: 17 AC, 1 DC, and 4 configurations with unknown charger type. They are not assigned speculative kW values. The 11 kW default is used only for the 522 AC-only labels that have no numeric rating.

## Connector evidence

Connector types are carried forward only from accepted A1 augmentation matches. They cover 214 stations: 84 with CCS2 and 130 with CCS2 plus CHAdeMO. These are station-level verified types, not physical connector-instance IDs.

## Generator input

The supplied generator and demo CSV were inspected. `data/input/stations.csv` passes the exact seven-column contract with 432 rows, 1,656 connectors, valid coordinates, positive power, and unique IDs. This supports 10,368 hourly-price rows for one day and a nominal 4,266 sessions at urban/regional rates of `3 2`. The generator itself was not run during P0.
