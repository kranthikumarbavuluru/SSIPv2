---
name: data-visualization
description: Design and implement clear, professional, accessible data visualizations for charts, graphs, analytics dashboards, infographics, trends, comparisons, distributions, relationships and geographic views. Use when Codex creates or improves SSIP dashboard metrics, chart selection, visual encoding, responsive chart layouts, legends, labels, tooltips, drill-down interactions, data stories or visualization accessibility in Python, Streamlit, HTML/CSS, JavaScript, D3.js or another existing project stack.
---

# Data Visualization

Create clear, accessible and decision-oriented data visualizations. Turn governed
data into charts, graphs, maps and dashboard views that help users understand
patterns, trends and actionable insights without distorting the evidence.

## Follow This Workflow

1. Inspect the existing application, data model and visualization stack.
2. Identify the user question the visualization must answer.
3. Confirm the data fields, units, grain, status definitions and missing values.
4. Select the simplest chart that represents the relationship accurately.
5. Define labels, scales, ordering, colors, annotations and accessibility needs.
6. Implement using the project's existing components and libraries when suitable.
7. Verify numerical accuracy, responsive layout, interaction and visual clarity.
8. Test desktop and mobile views and report any data gaps separately from defects.

Do not begin by choosing a visually impressive chart. Begin with the analytical
question and the structure of the data.

## Apply SSIP Data Rules

For the Startup Scheme Intelligence Platform:

- Calculate every total from the database or governed catalogue.
- Never fabricate values, dates, ministries, departments, sectors or AI scores.
- Keep schemes, programmes, calls, challenges, ecosystem support and historical
  records visually distinct.
- Do not combine `OPEN`, `UPCOMING`, `CLOSED` and `STATUS_UNVERIFIED` without a
  visible breakdown or clear definition.
- Display the relevant verification or update date near time-sensitive analysis.
- Label incomplete coverage and unverified information explicitly.
- Preserve official terminology while using concise chart labels.
- Treat empty, unknown and zero as different states.
- Avoid implying that record count equals funding impact or programme quality.
- Make filters and chart totals reconcile with the visible record population.

## Select the Chart from the Question

| User question | Recommended chart | Notes |
|---|---|---|
| How much or how many? | Horizontal bar, column | Prefer bars for long department or scheme names. |
| How has it changed over time? | Line, area, column | Use a continuous time axis and show missing periods. |
| What are the parts of a whole? | Stacked bar, 100% stacked bar, treemap | Prefer stacked bars when precise comparison matters. |
| How are values distributed? | Histogram, box plot, dot plot | Show sample size and meaningful bins. |
| How are two measures related? | Scatter, bubble | Do not imply causation from correlation. |
| Where are records located? | Map, choropleth | Normalize rates when regions differ greatly in size. |
| How do entities connect? | Network, Sankey, tree | Use only when relationships are central to the question. |
| What is the current composition? | Sorted bar, matrix, compact table | A table may be clearer for small exact datasets. |
| What happened across call years? | Horizontal stacked timeline/bar | Separate relevance or status groups consistently. |

Use pie or donut charts sparingly. Avoid them for many categories, similar values,
negative values or comparisons across multiple periods.

## Use Accurate Visual Encoding

Prefer encodings in this order when accuracy matters:

1. Position on a common scale
2. Position on separate aligned scales
3. Length
4. Angle or slope
5. Area
6. Color intensity

Use position and length for important comparisons. Do not encode precise values
only through area, angle or color.

Always:

- start bar-chart quantitative axes at zero unless a clearly labelled exception
  is analytically necessary;
- use consistent units, number formatting and date formats;
- sort categorical bars by value or a meaningful governed order;
- preserve chronological order for time;
- label axes and units;
- explain abbreviations;
- avoid dual axes unless the relationship cannot be communicated more honestly;
- show denominators for percentages; and
- disclose transformations, exclusions and filters that materially affect meaning.

## Design the Information Hierarchy

Use a dashboard hierarchy that supports scanning:

1. Page title and scope
2. Verification/coverage context
3. Primary outcome metrics
4. Main analytical visualization
5. Supporting comparisons
6. Detailed records or drill-down
7. Source and methodology notes

Keep metric cards concise. Pair a number with a meaningful label and, only when
supported by data, a comparison period or status explanation.

Use whitespace, alignment and grouping instead of excessive borders. Remove
decorative elements that do not improve comprehension.

## Use the SSIP Visual Direction

Follow the project's approved professional government-portal direction:

- light blue-and-white interface;
- restrained navy and government-blue accents;
- clean typography and readable density;
- accessible status badges;
- polished cards and analytics panels;
- minimal chart decoration;
- consistent spacing and radii; and
- responsive desktop and mobile layouts.

Reuse tokens and patterns from `assets/dashboard_theme.css`. Do not introduce an
unrelated chart palette or visual language without a clear project-wide reason.

## Build an Accessible Palette

- Do not rely on color alone; combine color with labels, icons, patterns or direct
  annotation when categories or statuses are important.
- Use no more than five to seven categorical colors in one chart.
- Use a sequential palette for ordered continuous values.
- Use a diverging palette only when the data has a meaningful midpoint.
- Reserve strong warning colors for genuine warnings, failures or urgent states.
- Maintain a text contrast ratio of at least 4.5:1 for normal text.
- Test colors in both light and dark modes when the page supports both.
- Keep the meaning of a status color consistent across the dashboard.

For SSIP, do not make `STATUS_UNVERIFIED` look equivalent to verified `OPEN`.
Keep historical and closed records visually available but distinct from current
application opportunities.

## Use Clear Typography and Labels

- Use approximately 12–14 px for labels and 16–18 px or more for chart titles,
  adjusted to the existing responsive type scale.
- Use tabular figures for aligned numerical metrics when supported.
- Prefer direct labels over legends when space permits.
- Write titles that state what the chart shows, not merely the chart type.
- Add a short subtitle for scope, period, filters or verification date.
- Shorten long organisation names carefully and expose the full name in a tooltip
  or accessible label.
- Avoid rotated axis labels when a horizontal chart would be more readable.

## Design Interaction Deliberately

Use interaction only when it helps users answer a question.

- Provide hover/focus tooltips for exact values and supporting context.
- Support keyboard focus for interactive marks and controls.
- Make click-to-filter or drill-down behaviour visible and reversible.
- Provide reset/clear actions for compound filters.
- Preserve selected filters across related views when that behaviour is expected.
- Use transitions of roughly 300–500 ms only when they clarify a state change.
- Avoid animation that delays reading or obscures comparisons.
- Make touch targets at least 44 px where practical.

Tooltips should include the entity, value, unit, status or category and relevant
time period. They should not contain essential information that keyboard or touch
users cannot otherwise access.

## Implement Responsive Visualizations

- Use flexible containers and scalable SVG `viewBox` when appropriate.
- Reduce tick density at smaller breakpoints.
- Move legends or use direct labels on narrow layouts.
- Change multi-column dashboards to one-column flow on mobile.
- Prefer horizontal scrolling only for genuinely wide detailed tables, not core
  charts.
- Ensure chart labels do not overlap or become clipped.
- Consider a mobile-specific chart form if scaling alone makes the view unreadable.

For a card grid, define explicit desktop, tablet and mobile column counts. For a
chart, test at representative desktop and mobile widths rather than assuming the
library's responsive option is sufficient.

## Provide Nonvisual Alternatives

For every material chart:

- provide an accessible name and concise description;
- expose exact values in tooltips, labels or a companion table;
- describe the main insight in nearby text when appropriate;
- preserve logical keyboard and screen-reader order; and
- make downloadable or tabular data available when the existing product pattern
  supports it.

Do not use an image of a chart as the only data representation.

## Prefer the Existing Technology Stack

Inspect installed dependencies and existing components before adding a library.
Use the simplest compatible implementation.

Common options include:

- native Streamlit charts or components for simple SSIP views;
- HTML/CSS for compact bars, progress tracks and card-based distributions;
- Plotly, Altair or another already-installed Python library for interaction;
- D3.js for highly custom SVG visualizations;
- Chart.js, Recharts or Victory in compatible JavaScript applications; and
- Tableau or Power BI only when the task explicitly targets those platforms.

Do not add a dependency merely to render a visualization that existing project
code can express clearly.

## Follow a Standard D3 Pattern When D3 Is Appropriate

```javascript
const svg = d3.select("#chart")
  .append("svg")
  .attr("role", "img")
  .attr("aria-labelledby", "chart-title chart-description")
  .attr("viewBox", [0, 0, width, height]);

const x = d3.scaleLinear()
  .domain([0, d3.max(data, d => d.value)])
  .nice()
  .range([margin.left, width - margin.right]);

svg.selectAll("rect")
  .data(data, d => d.category)
  .join("rect")
  .attr("x", margin.left)
  .attr("y", d => y(d.category))
  .attr("width", d => x(d.value) - margin.left)
  .attr("height", y.bandwidth());
```

Use keyed data joins, explicit margins, deterministic scales and accessible SVG
metadata. Sanitize any untrusted text before inserting it into HTML tooltips.

## Use Safe Tooltip and Resize Patterns

```javascript
element.on("mouseenter focus", (event, d) => {
  tooltip
    .style("opacity", 1)
    .text(`${d.category}: ${formatValue(d.value)}`);
});

const resize = () => {
  const width = container.clientWidth;
  svg.attr("width", width);
  x.range([margin.left, width - margin.right]);
  render();
};

window.addEventListener("resize", resize);
```

Prefer `.text()` for untrusted values. If HTML is necessary, escape values before
insertion. Debounce expensive resize handlers in complex charts.

## Avoid Common Visualization Failures

Do not:

- use 3D charts;
- truncate bar axes deceptively;
- use rainbow gradients for ordered quantitative data;
- overload one chart with too many categories or labels;
- hide missing or unverified data;
- show precision unsupported by the source;
- compare totals with incompatible scopes or periods;
- duplicate the same information across many chart types;
- animate every dashboard update;
- place essential meaning only in hover states;
- use maps when geography is not analytically relevant; or
- display a chart when two numbers or a small table would be clearer.

## Verify Before Completion

Check all of the following:

- Chart values reconcile with the filtered source records.
- Totals and percentages use the correct denominator.
- Category and status mappings are governed and explainable.
- Axes, labels, units, legends and dates are correct.
- Sorting and time order are intentional.
- Empty, loading, error and no-match states are readable.
- Tooltips and filters work with mouse and keyboard where applicable.
- Color is not the only carrier of meaning.
- Desktop, tablet and mobile layouts remain readable.
- Light/dark themes remain legible where supported.
- Official links and drill-down targets open correctly.
- The application has no runtime or console errors.
- Relevant automated tests and visual checks pass.

Report unresolved data-quality limitations separately from software defects.

