# Migration `radio_clicks` (20261013T123033_radio_clicks)

Owner feedback (2026-10-13): the radio effect lacked MCC's opening and closing clicks. `radio.clicks` turned on where the Spain original opens with the click (similarity >= 0.75). Mode: **write**.

- Changed: **35**; left off: 5.
- File before: `95e8be510cfd659a2e68411056a646f2b578ced2182ed41706d0c1bf84cc6cf6`; after: `7543d2a5f4a7138929ba95c126c720cca8f49b7cd53283e6876ac5b489ff4ce2`

| Mapping | Slot | Audio | Spain intro similarity |
|---|---|---|---|
| `m-000054` | `es:A10_643_cortana#0` | needs_rework | 0.981 |
| `m-000177` | `es:lif_02#0` | needs_rework | 0.912 |
| `m-000178` | `es:lif_04#0` | needs_rework | 0.915 |
| `m-000481` | `es:C10_200_pilot#0` | needs_rework | 0.909 |
| `m-000487` | `es:C10_extract_050_pilot#0` | needs_rework | 0.887 |
| `m-000488` | `es:C10_insert_030_Pilot#0` | needs_rework | 0.903 |
| `m-000489` | `es:C10_insert_040_pilot#0` | needs_rework | 0.897 |
| `m-000490` | `es:B40_insert_020_pilot#0` | needs_rework | 0.895 |
| `m-000491` | `es:C10_insert_050_pilot#0` | needs_rework | 0.903 |
| `m-000492` | `es:C10_230_pilot#0` | draft | 0.914 |
| `m-000507` | `es:D40_410_pilot#0` | needs_rework | 0.892 |
| `m-000510` | `es:B40_040_bisenti#0` | needs_rework | 0.988 |
| `m-000536` | `es:B30_350_pilot%202#0` | needs_rework | 0.915 |
| `m-000537` | `es:B30_020_bisenti#0` | needs_rework | 0.988 |
| `m-000539` | `es:A30_1030_pilot#0` | needs_rework | 0.91 |
| `m-000558` | `es:A30_1040_pilot#0` | needs_rework | 0.911 |
| `m-000560` | `es:A30_insert_020_LifeboatPilot#0` | needs_rework | 0.882 |
| `m-000563` | `es:A30_EXTRACT_050_PILOT#0` | needs_rework | 0.904 |
| `m-000566` | `es:A30_EXTRACT_020_PILOT#0` | needs_rework | 0.888 |
| `m-000568` | `es:A30_990_pilot#0` | needs_rework | 0.91 |
| `m-000569` | `es:A30_980_pilot#0` | needs_rework | 0.907 |
| `m-000570` | `es:A30_970_pilot#0` | needs_rework | 0.909 |
| `m-000572` | `es:A30_930_pilot#0` | needs_rework | 0.91 |
| `m-000574` | `es:A30_1080_pilot#0` | needs_rework | 0.918 |
| `m-000575` | `es:A30_250_pilot#0` | needs_rework | 0.918 |
| `m-000576` | `es:A30_261_pilot#0` | needs_rework | 0.907 |
| `m-000577` | `es:A30_300_pilot#0` | needs_rework | 0.863 |
| `m-000578` | `es:A30_340_pilot#0` | needs_rework | 0.886 |
| `m-000579` | `es:A30_350_pilot#0` | needs_rework | 0.79 |
| `m-000580` | `es:A30_370_pilot#0` | needs_rework | 0.914 |
| `m-000585` | `es:A30_210_bisenti#0` | needs_rework | 0.987 |
| `m-000586` | `es:A30_220_bisenti#0` | needs_rework | 1.0 |
| `m-000588` | `es:A30_720_Bisenti#0` | needs_rework | 0.99 |
| `m-000597` | `es:A30_720_Mendoza#0` | needs_rework | 0.915 |
| `m-000647` | `es:A50_710_bisenti#0` | needs_rework | 0.996 |

Left without clicks:

- `es:sgt05g#0` (needs_rework, similarity 0.025): the Spain original has no opening click
- `es:lif_01#0` (needs_rework, similarity 0.118): the Spain original has no opening click
- `es:lif_05#0` (needs_rework, similarity 0.26): the Spain original has no opening click
- `es:c10_010_captpilot#0` (needs_rework, similarity 0.143): the Spain original has no opening click
- `es:D40_411_Pilot#0` (needs_rework, similarity 0.031): the Spain original has no opening click

## Verification

- written_sha_matches: True
- result_equals_plan: True
- only_the_radio_clicks_changed: True
- no_approved_audio_changed: True
