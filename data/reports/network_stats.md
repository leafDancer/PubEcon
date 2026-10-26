# Coauthor network statistics

Generated 2026-10-26T15:49:16+00:00.

The graph is an unweighted, undirected coauthorship network of canonical authors. One edge means two authors shared at least one research article; multiple shared papers do not shorten the path. Average path length and diameter are computed over unordered pairs in the largest connected component. Authors outside that component are reported separately and are not treated as infinitely distant.

| Scope | Authors | Ties | Components | Largest | Avg. path | Diameter | Clustering |
|---|---|---|---|---|---|---|---|
| ALL | 9494 | 19728 | 708 | 7466 | 6.58 | 18 | 0.678 |
| AER | 5463 | 8244 | 745 | 3061 | 8.05 | 23 | 0.739 |
| ECMA | 2170 | 2875 | 390 | 849 | 9.69 | 24 | 0.762 |
| JPE | 2318 | 2901 | 495 | 423 | 10.74 | 27 | 0.820 |
| QJE | 1957 | 4734 | 290 | 1010 | 7.10 | 18 | 0.812 |
| RES | 2684 | 3407 | 535 | 564 | 10.46 | 26 | 0.796 |

## Reading the numbers

- **Average path** is the mean number of coauthorship steps between two authors in the largest component, not between all 10,000+ authors.
- **Diameter** is the longest shortest path in that component.
- **Clustering** is the mean local clustering coefficient: how often two coauthors of an author also coauthor with each other.
- A journal scope uses only papers in that journal, so an author can have a different component and path length in each journal.
