# Mexico report-template versions -- browser check

8/8 PASS

| Check | Result |
|---|---|
| t-0 nothing is stacked under the page before a template is selected | PASS |
| t-5 Mexico shows one versions tab ('Versions & gates'; built-in 'Versions' hidden) | PASS |
| t-1 the selected template's versions are listed with the platform gate answer (and no other template) | PASS |
| t-2 'New version' creates a Draft copy with the same fields, listed under the template | PASS |
| t-3 compare shows the copy has the same fields (only its version metadata differs) | PASS |
| t-6 'Open' on an older version opens its detail (replaces the hidden built-in Versions tab) | PASS |
| t-4 an organisation admin is refused the template versions route | PASS |
| z1 no 5xx responses and no page errors | PASS |

4xx responses seen in the browser: none
Console errors: none
