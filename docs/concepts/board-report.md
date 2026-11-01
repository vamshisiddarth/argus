# Decision board

A scan can return hundreds of findings. The decision board turns a scan report
into one page that groups them into [opportunities](opportunities.md) and lets a
person mark each one Approve, Investigate or Keep. It is a single HTML file: no
server, no login, no network requests.

```bash
argus board --report local_reports/aws/2026/10/30/<scan>.json
# writes <scan>.board.html next to the report; --out chooses another path
```

It needs only the JSON report. It works with reports from earlier versions too,
because the opportunities are rebuilt from the findings when a report has none.
See a built example in `examples/sample-board.html` (made-up data; regenerate it
with `python examples/make_sample_board.py`).

## What is on the page

| Part | What it shows |
|------|---------------|
| Header | The Argus logo and name, the page title, and the scan date, account count and finding count |
| Tally (sticky) | Approved a month, investigating, kept and undecided; export decisions, export CSV, import decisions, clear all |
| Overview | A "Read before deciding" banner when the scan reported warnings (for example no resource-level cost data); KPI cards (reported waste, opportunities, billed share, unpriced findings, resources analysed, cost of this run); where the money is (dollars by cost basis, and the Easy and Needs-an-owner lanes); cost of this run |
| Decide | A filter rail (lane, decision, action, search) and a grid of opportunity cards |
| Kept on purpose | Everything marked Keep, with its reason and expiry |
| About this report | Collapsed in the footer: scan id, schema version, coverage, definitions and limits |

The layout uses the whole width: the cards flow into as many columns as fit, the
filter rail sits beside them on wide screens and becomes a bar across the top on
narrower ones.

### An opportunity card

Each card carries a savings range (billed plus list-priced dollars up to adding
the model's estimates) with a chip for every cost basis, its lane, action and
confidence, a one-line **risk**, collapsible **evidence** and **check-first**
steps, the full member list, and the owners found in tags. The text is built from
templates and the members' own data, without a model.

## Decisions

| Decision | Meaning |
|----------|---------|
| Approve | You want this done. It counts in the approved total |
| Investigate | An owner should look first. It counts as "at stake", not as approved |
| Keep | It stays on purpose. A reason is required, and an optional date says until when |

Decisions are stored in the browser (local storage) and are keyed by the
opportunity's stable id, so they still apply to a later scan. To share them,
export the decisions file and import it elsewhere; when the same opportunity was
decided twice, the newer decision wins. The CSV export lists every opportunity
with its range and decision; cells that start with `=`, `+`, `-` or `@` are
escaped so a spreadsheet cannot run them. Argus never changes a resource:
approving here only records a decision.

## Cost of this run

The KPI card and panel show what the scan cost to run, taken from the report:
model spend against the budget and against the estimate made before the run,
model calls and tokens, the cost per 1,000 resources analysed, and the billed and
list-priced waste found per $1 of model spend. That last figure is waste found,
not savings realized. The report does not record AWS API charges (for example Cost
Explorer requests) or the cost of the place Argus runs, so those are not included.

## Safety

The page sets a Content Security Policy that allows only its own inline style and
script, by hash. There are no inline style attributes, no event-handler attributes,
no images or fonts from outside, and no network requests. Every string that comes
from the scan (names, tags, reasons) is escaped, and the embedded data cannot close
its own script tag.

## Accessibility

Native buttons, inputs and labels; toggle buttons expose their state; the tally,
filter count and status line are polite live regions; a skip link; visible focus;
reduced-motion support; light and dark themes (the `#theme=dark` or `#theme=light`
URL fragment forces one). Colour pairs are tested for WCAG AA contrast, and the
page was scanned with axe in both themes at five widths.

## Limits

- The action of an opportunity is read from the wording of each recommendation, so
  unusual wording falls back to Review.
- Decisions live in one browser unless exported; there is no shared state.
- Commitments (Savings Plans, reservations) are not analysed.
- This static page is deliberately plain. A richer dashboard is planned for the
  product frontend.
