# ATS China Job Discovery MVP

This MVP discovers company ATS board tokens from manually collected search result URLs, then fetches current public jobs from supported ATS public APIs.

It does not scrape LinkedIn, Google, Bing, Indeed, Workday, iCIMS, or custom career pages.

## Supported ATS platforms

- Greenhouse
- Lever
- Ashby
- SmartRecruiters
- Recruitee

## Prepare `data/search_results.csv`

Create or edit:

```text
ats_china_job_discovery/data/search_results.csv
```

Required columns:

- `source_query`
- `result_url`

Optional columns:

- `result_title`
- `discovered_keyword`

Example:

```csv
source_query,result_url,result_title,discovered_keyword
site:boards.greenhouse.io China,https://boards.greenhouse.io/examplecompany/jobs/123456,Example Job,China
site:jobs.lever.co Shanghai,https://jobs.lever.co/examplecompany/abc-def,Example Job,Shanghai
site:jobs.ashbyhq.com APAC,https://jobs.ashbyhq.com/examplecompany/123,Example Job,APAC
site:jobs.smartrecruiters.com Beijing,https://jobs.smartrecruiters.com/ExampleCompany/123456,Example Job,Beijing
site:recruitee.com APAC,https://examplecompany.recruitee.com/o/example-job,Example Job,APAC
```

If `data/search_results.csv` only contains the header row, the export files will also only contain headers. Add real Greenhouse, Lever, Ashby, SmartRecruiters, or Recruitee job URLs before running.

Search results are only company discovery signals. Final job data comes from public ATS APIs whenever possible.

## Install

Use Python 3.10+.

```bash
cd ats_china_job_discovery
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On macOS/Linux, activate with:

```bash
source .venv/bin/activate
```

## Run

```bash
python main.py
```

Optional paths:

```bash
python main.py --input data/search_results.csv --db output/ats_jobs.db --exports output/exports
```

## Optional: semi-automated discovery

You can keep manually editing `data/search_results.csv`, or use `discover.py` to find candidate ATS URLs through a search API.

Prepare search queries in:

```text
data/search_queries.csv
```

The script uses SearchApi's Google endpoint and requires an API key:

```bash
set SEARCHAPI_API_KEY=your_api_key_here
python discover.py
```

It writes candidates to:

```text
output/review/discovery_candidates.csv
```

Review that CSV and set `status` to:

- `accepted`: append this candidate to `data/search_results.csv`
- `rejected`: ignore this candidate
- `pending`: leave undecided

Then import the reviewed file:

```bash
python discover.py --import-review output/review/discovery_candidates.csv
```

After accepted rows are appended to `data/search_results.csv`, run the normal fetch:

```bash
python main.py
```

The discovery step does not scrape Google or Bing pages directly. It uses a search API only to find ATS company tokens; final job data still comes from public ATS APIs.

## Outputs

The script creates or updates:

- `output/ats_jobs.db`: SQLite database with discovered companies and normalized jobs.
- `output/exports/recent_china_related_jobs.csv`: current jobs with China/APAC keyword matches and a recent recency status.
- `output/exports/recent_china_related_companies.csv`: companies with at least one recent China/APAC keyword-hit job.

The jobs export includes:

- company and ATS identifiers
- `ats_job_id` and `ats_board_token`
- title and raw location
- recency status
- `fetch_status`: `success`, `redirect_failed`, `content_empty`, `closed`, or `error`
- ATS published/updated dates when available
- first seen date
- matched China/APAC keywords
- original public job URL and `normalized_url`
- `jd_text` and `jd_text_length`

## Recency rule

The script uses the local date from the Python runtime.

- `recent_published`: ATS published date is within the last 30 days.
- `recent_updated`: ATS updated date is within the last 30 days.
- `newly_seen`: the job was first seen by this local system within the last 30 days.
- `current_but_old_or_unknown`: the job is current but does not meet the recent published, updated, or first-seen checks.

## Keyword matching

Keywords are searched in job title, location, and description. The list includes China, major China city names, APAC/Asia Pacific phrases, China/Asia remote phrases, China timezone, and Mandarin.

## Known limitations

- Company names are guessed from ATS tokens unless the ATS response includes a company name.
- SmartRecruiters list responses vary by company; detail fetching is disabled by default for speed. Set `SMARTRECRUITERS_FETCH_DETAILS=1` if you want per-job details.
- API schemas can vary across ATS platforms and companies, so raw JSON is stored for debugging.
- The system does not evaluate resume fit or seniority fit.
- The system does not search the web itself; `search_results.csv` is manually prepared input.
