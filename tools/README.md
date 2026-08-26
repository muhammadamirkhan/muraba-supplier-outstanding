# Tools

Run from anywhere in the project; each resolves the BC secret the same way the
app does (env `BC_CLIENT_SECRET` → Streamlit secrets → the credentials note on
G:). Read-only — none of them write to BC.

| Script | What it's for |
|---|---|
| `health_check.py` | Is BC reachable, are the three feeds intact. Run this first when anything looks wrong. |
| `trace_tag.py VLLC0360` | Full audit trail for one supplier's category: every invoice line, the G/L account each posts to, the totals, and how that resolves to the tag — plus the BC screens to verify it in. Use this when the client questions a tag. |
| `vendor_ledger.py "Al Hai"` | Raw BC ledger entries for one vendor (number or name fragment), and the figures the dashboard derives from them. Use when a supplier's numbers look wrong. |
| `export_categories.py` | Regenerates `../supplier_categories.csv` — every supplier, its tag, the G/L account behind it, and current figures. |
| `test_pipeline.py` | Headless end-to-end check: identity `invoiced − paid = outstanding`, no negative figures, no `-0`, template renders. **Run before pushing.** |

`_common.py` is shared bootstrap, not a tool.
