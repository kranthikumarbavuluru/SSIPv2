# SSIP v3.4.3.8.1.2 — Quick Editor Type, Stage and CSV Export

This continuation adds the requested Quick Editor fields.

## TYPE checkboxes

- All
- Individual
- Startup

`All` stores both Individual and Startup. A record may also be limited to one type.

## STAGE checkboxes

- All
- Ideation
- Validation
- Scaling
- Early Traction

`All` stores all four stages. Multiple individual stages may be selected.

## CSV download

The Quick Editor page includes a `Download filtered CSV` button. The download follows the active Ministry, Department and Search filters and includes category, status, type, stage, minimum funding and maximum funding.

## Write behaviour

Type and stage values are written into the governed record JSON and audit history. When matching staging columns exist, they are also synchronized. Published records remain protected and are saved for separate publication review.

No publication is performed during installation.
