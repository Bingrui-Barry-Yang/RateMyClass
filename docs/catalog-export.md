# Catalog export format

The Occidental course catalog that RateMyClassOxy scrapes from counts.oxy.edu, published for
other projects (for example a course planner) so they do not have to scrape it themselves.

- **Files:** `make export` writes them from the database to `data/export/`. `make import` runs it
  after every successful import.
- **API:** the read-only `/api/v1` returns the same models (see [API](#api)).
- **Code:** the models are in `backend/app/schemas/catalog_export.py` and the queries in
  `backend/app/services/catalog_export.py`.

## Files

| File | Contents |
| --- | --- |
| `catalog-index.json` | Terms, departments and Core areas |
| `catalog-<term>.json` | Every section of one term (`catalog-202702.json`), each with its course and professors embedded, so one file is enough to search and build schedules for that term |
| `courses.json` | Every course, with the numbers and terms it was offered under, its description history and related courses |
| `professors.json` | Every professor, with the departments they taught in |

Every file is UTF-8 JSON and has two top-level fields:
- `schema_version`: currently `1`;
- `generated_at`: UTC time of the export, e.g. `"2026-11-15T23:51:11Z"`.

Lists come in a fixed order, so two exports of unchanged data differ only in `generated_at`:
- sections by CRN;
- courses and professors by key;
- terms and departments by code.

## Identifiers

Refer to catalog rows only by these natural keys, never by database ids.

| Row | Key | Example |
| --- | --- | --- |
| Term | `code` | `202702` |
| Department | `code` | `COMP` |
| Section | `(term, crn)` | `("202702", "2763")`. A CRN is unique only within one term; terms reuse CRNs |
| Course | `key` | `COMP-131`; `COMP-395-deep-learning` (one topic of a topics course); `FYS-a-foodie-s-philosophy` (first-year seminars are grouped by title, without their number); `BIO-103-untitled-williams-jonathan-p` (a topics section with only the generic title) |
| Professor | `key` | `camarillo-abad-hector-miguel` (last name + first names) |

**Course and professor keys can change.** This happens when a renumbered course is merged, an
untitled topics section gets a new professor, or a hand correction is made. RateMyClassOxy will
redirect old keys to new ones on its pages.

A section the site drops (a cancelled class) disappears from the next export. A section whose
time or professor changes keeps its `(term, crn)`.

## Term codes

`YYYYTT`:
- `YYYY` is the year the academic year **ends**;
- `TT` is `01` fall, `02` spring or `03` summer.

For example, `202701` is 2026 Fall, `202702` is 2027 Spring and `202703` is 2027 Summer. Codes sort
in time order.

## `catalog-index.json`

```json
{
 "schema_version": 1,
 "generated_at": "2026-11-15T23:51:11Z",
 "terms": [{"code": "202702", "label": "2027 Spring", "year": 2027, "season": "spring", "academic_year": "2026-27"}],
 "departments": [{"code": "COMP", "name": "Computer Science"}],
 "core_areas": [{"code": "CPLS", "name": "Core Laboratory Science"}]
}
```

- `terms[].year` is the calendar year the term is in.
- First-year seminars are the department `FYS` ("First Year Seminar").
- `core_areas` lists every Core code the site has used, with its name as the site shows it:

  | Code | Name |
  | --- | --- |
  | `CPUD` | Core United States Diversity |
  | `CPRF` | Core Regional Focus |
  | `CPGC` | Core Global Connections |
  | `CPPE` | Core Pre-1800 |
  | `CPFA` | Core Arts |
  | `CFAP` | Core Arts Partial |
  | `CPMS` | Core Mathematics/Science |
  | `CPLS` | Core Laboratory Science |
  | `LANG` | Core Language Proficiency |

## `catalog-<term>.json`

```json
{
 "schema_version": 1,
 "generated_at": "2026-11-15T23:51:11Z",
 "term": {"code": "202702", "label": "2027 Spring", "year": 2027, "season": "spring", "academic_year": "2026-27"},
 "sections": [
  {
   "term": "202702", "crn": "2765", "code": "COMP 131 1-2", "kind": "lab",
   "section": "1", "lab_section": "2", "parent_crn": "2763",
   "title": "Fundamentals of Computer Science Laboratory", "units": 0,
   "meetings": [{"time": "01:20pm-04:10pm", "days": "T"}],
   "core": [{"code": "CPLS", "name": "Core Laboratory Science"}],
   "seats_max": 18,
   "cross_list_group": null,
   "professors": [{"key": "walsh-joel-anderson", "display_name": "Joel Anderson Walsh"}],
   "course": {
    "key": "COMP-131", "dept": "COMP", "number": "131",
    "title": "Fundamentals of Computer Science", "full_title": "Fundamentals of Computer Science",
    "is_topic": false, "units": 4, "description": "…",
    "restrictions": [], "prerequisites": [], "corequisites": null, "repeatable": false
   }
  }
 ]
}
```

| Field | Meaning |
| --- | --- |
| `code` | The course code as listed: department, number, section and an optional lab section |
| `kind` | `lecture` or `lab` |
| `section`, `lab_section` | `COMP 131 1-2` is section `1`, lab section `2`; `lab_section` is null for lectures and for `224L`-style labs |
| `parent_crn` | For a dash lab (`COMP 131 1-2`), the CRN of its lecture (`COMP 131 1`) in the same term. Null for lectures and for labs with their own number (`PHYS 110L 1`), which belong to the same course but to no particular lecture. A few dash labs have no matching lecture on the site and also have null (`MATH 110 1-1` in 202303, whose lecture is `MATH 110 0`; `COMP 239A 1-1` in 202701, whose lecture is `COMP 239 1`): never assume a dash lab has a parent |
| `title` | The title as listed that term (labs have their own) |
| `units` | Credit units, an integer; labs are often 0 |
| `meetings` | One entry per meeting pattern (see below) |
| `core` | Core areas the site marks on this section |
| `seats_max` | Maximum seats as of the latest download. Enrollment and waitlist are not included |
| `cross_list_group` | Same value for the copies of one class listed under several departments (same term, professors and time), e.g. `"202101:AMST 376 0+BLST 376 0"`. Use it to group or label cross-listed sections, not as a stored reference: it changes when its members change |
| `professors` | In listed order; empty when the site lists no instructor ("Instructor Unassigned") |
| `course` | The course this section belongs to. `description` is the wording of this section's term |

### Meetings

- `time` is `hh:mmam-hh:mmpm` (12-hour clock, zero-padded), or `Time-TBD`.
- `days` is a string of day letters: `M` Monday, `T` Tuesday, `W` Wednesday, `R` Thursday,
  `F` Friday, `S` Saturday, `U` Sunday (e.g. `MWF`, `TR`), or `Days-TBD`.
- A section without a fixed time (directed research, for example) has
  `[{"time": "Time-TBD", "days": "Days-TBD"}]`.
- About 3% of sections have two to four entries, e.g. a lecture plus an extra weekly meeting:
  `[{"time": "08:30am-09:55am", "days": "TR"}, {"time": "07:00pm-09:00pm", "days": "M"}]`.
  Check each entry for time filters and conflicts.

### Labs

Labs come in two forms:
1. **A separate CRN:**
   - either a dash lab (`COMP 131 1-2`, `kind: "lab"`, with `parent_crn`, null in the rare cases where the site lists no matching lecture);
   - or a lab with its own number (`PHYS 110L 1`, `kind: "lab"`, no `parent_crn`).
2. **Extra meetings of the lecture under the same CRN:** extra entries in `meetings`.

## `courses.json`

```json
{
 "schema_version": 1,
 "generated_at": "2026-11-15T23:51:11Z",
 "courses": [
  {
   "key": "AMST-233", "dept": "AMST", "number": "233",
   "title": "…", "full_title": "…", "title_variants": ["…"],
   "numbers": [{"number": "233", "terms": ["202102"]}],
   "is_topic": false, "units": 4,
   "description": "…",
   "description_history": [{"from_term": "202102", "to_term": "202102", "text": "…"}],
   "restrictions": ["Graduate students may not enroll in this class."],
   "prerequisites": [],
   "corequisites": null,
   "repeatable": false,
   "related": [{"key": "AMST-333", "relation": "now"}]
  }
 ]
}
```

| Field | Meaning |
| --- | --- |
| `title` | Display title: the latest lecture title; for a topics course, only the topic |
| `full_title` | The title as listed (e.g. with "Special Topics in …") |
| `title_variants` | Every spelling seen |
| `numbers` | Every number the course was listed under, with its terms. A renumbered course has several entries (e.g. PHYS 266 then 206). Use it to show former numbers, not as the list of terms the course was offered: terms where only a lab with its own number ran (`PHYS 240L` in 202201 while `PHYS 240` itself did not run) are missing. For "offered in these terms", check which `catalog-<term>.json` files have a section of the course |
| `description` | The latest wording |
| `description_history` | One entry per wording, with the first and last term it was used |
| `restrictions` | As listed |
| `prerequisites` | Rows of the site's prerequisite table as listed. Connectives stay in `course` (`"or MATH 210"`, `"(and MUSC 151"`), so treat it as text to display, not as rules |
| `corequisites` | Free text or null |
| `repeatable` | The site says the course may be repeated for credit |
| `related` | Separate courses that are connected. `formerly`: the other course came before this one; `now`: the other course replaced this one; `see_also`: a close relative |

## `professors.json`

```json
{
 "schema_version": 1,
 "generated_at": "2026-11-15T23:51:11Z",
 "professors": [
  {"key": "camarillo-abad-hector-miguel", "display_name": "Hector Miguel Camarillo Abad",
   "first_name": "Hector Miguel", "last_name": "Camarillo Abad", "departments": ["COMP", "FYS"]}
 ]
}
```

`departments` are the departments of the courses the professor taught.

## Coverage

- **Terms:** every term counts.oxy.edu lists, from 2020 Fall (`202101`). Terms the site later
  drops are kept.
- **Not included:**
  - study abroad (`AB*` departments);
  - private music lessons (`MUSA`);
  - "Credit by Exam" listings.
- **Not on the site, so not here:** classrooms, textbooks and exam times.
- **Updates:** RateMyClassOxy re-downloads changed and new terms (`make update`), reviews the
  change report and imports it (`make import`). The export follows each import, and
  `generated_at` shows when it was made.

## API

The same data, read live from RateMyClassOxy's database. No login. Paths are under the site's
`/api` prefix (locally `http://localhost:8010/api/v1/...`; the public address comes with launch).

| Endpoint | Returns | Same as |
| --- | --- | --- |
| `GET /api/v1/terms` | list of terms | `terms` of `catalog-index.json` |
| `GET /api/v1/departments` | list of departments | `departments` of `catalog-index.json` |
| `GET /api/v1/core-areas` | list of Core areas | `core_areas` of `catalog-index.json` |
| `GET /api/v1/catalog?term=202702` | every section of one term | `catalog-202702.json` |
| `GET /api/v1/courses/{course_key}` | one course | an entry of `courses.json` |
| `GET /api/v1/professors/{professor_key}` | one professor | an entry of `professors.json` |

- **Unknown term or key:** `404` with `{"detail": "..."}`. A missing `term` is `422`.
- **`generated_at`** (in `/catalog`) is the same as in the files: when RateMyClassOxy last
  published the data (the export that follows each import). Show it as "data updated on …".
- **Caching:** every response has an `ETag` and `Cache-Control: public, max-age=300`. Send the
  ETag back in `If-None-Match` to get `304 Not Modified` (no body) while the data is unchanged.
  The data changes only when RateMyClassOxy imports a new download.
- **Compression:** responses are gzipped when the request accepts it (a term's catalog is about
  1.1 MB, about 170 KB gzipped).
- **Browser calls (CORS):** only sites RateMyClassOxy lists may call it from a browser; only `GET`.
  Server-side calls are not limited by this.
- **Types:** the OpenAPI schema is at `/api/openapi.json` (endpoints tagged `public v1`), e.g. for
  `openapi-typescript`.
- **Redirects** from changed course or professor keys to new ones are not there yet: an old key
  is a `404` for now.

## Versioning

- Adding a field is not a breaking change: ignore fields you do not know.
- Renaming or removing a field, or changing what it means, increases `schema_version` (and the
  API moves to `/api/v2`). The previous version is kept available for a while.
