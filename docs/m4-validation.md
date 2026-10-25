# M4 spot checks

This is a small, non-random validation log for the ORCID/CV career layer. It records concrete cases that were checked against the source and the parser fixes they triggered. It is not a precision estimate.

## ORCID identity validation

OpenAlex author links are not reliable enough to use an ORCID without checking it. The validation pass compares each ORCID record with the author's AER papers and affiliations.

**Rejected cases (wrong person, events cleared):**

- **Gavin Wright** — ORCID `0000-0002-7000-9305` is a surgical oncologist at St Vincent's Hospital Melbourne, not the Stanford economic historian. Works include thoracic surgery and lung cancer; the record is rejected as a field mismatch.
- **Ayşegül Şahin** — ORCID `0000-0001-5795-2852` is a Turkish physiotherapist (Bezmialem Vakıf Üniversitesi), not the economist at the University of Texas at Austin. Rejected as a field mismatch.
- **Paolo Angelini** — ORCID `0000-0001-5014-1707` is a cardiologist at the Texas Heart Institute, not the Bank of Italy economist. Rejected as a field mismatch.
- **Tom Nicholas** — ORCID `0000-0001-5889-6864` lists a PhD in Drama from the University of Exeter; the AER author is an economic historian at Harvard Business School. Rejected as a field mismatch.
- **Andrew B. Bernard** — ORCID `0000-0001-7205-0187` lists a PhD-candidate position at the University of Michigan from 2015; the Dartmouth trade economist had published in the AER since 2000. Rejected as a field mismatch.
- **Navin Kartik** — ORCID `0009-0003-5604-4483` is a commerce/computer-applications academic at Presidency College and Manipal Academy, not the Columbia economic theorist. Rejected because a dated assistant-professorship would have changed the career stage without positive identity evidence.
- **Patrick Bayer** — ORCID `0000-0003-1731-1270` is a political scientist at Glasgow/Strathclyde, not the Duke economist. Rejected for the same reason.

**Accepted cases, including movers and sparse records:**

- **Daron Acemoglu** — the ORCID legal name is "K. Acemoglu", while the credit name is "K. Daron Acemoglu". The first validation pass rejected it on the legal name alone; the parser now checks credit names and other-name variants, accepts the MIT institution match, and assigns full professor at low confidence for all 29 AER papers.
- **Anthony Wray** — ORCID work DOI matches the 2024 AER paper. The ORCID itself is sparse, but the CV supplies Associate Professor, University of Southern Denmark, 2022–present; the assignment is correct.
- **Mark Duggan** — ORCID institution (Stanford) matches the 2014–2016 AER bylines. The generic "Professor" event is capped at medium by the institution tier and the assignment remains low confidence because the title may be stale.
- **Alexander V. Hirsch** — ORCID (Caltech) matches the 2015 AER byline. The generic "Professor" event is low confidence; the person may have been an assistant professor at the time.
- **Bruno S. Frey** — ORCID affiliation is CREMA / University of Basel, with 203 economics works. Accepted at low confidence through the economics-field tier; the 2004 AER paper is assigned `non_academic` (Research Director, CREMA).
- **Alicia Sasser Modestino** — ORCID has a Federal Reserve Bank of Boston position and a Harvard economics PhD. Accepted at low confidence; the 2026 AER paper is assigned associate professor at Northeastern.
- **Tobias Kretschmer** — ORCID LMU Munich / Imperial College overlaps the AER byline institution; accepted at medium confidence and assigned professor at LMU.
- **Nikos Nikiforakis** — the ORCID record has only an NYU Abu Dhabi employment entry with no title or dates. It is retained as an unverified low-confidence identity link, but its events are withheld; the 2011 AER paper remains unknown.
- **Lars E. O. Svensson** — the ORCID record has only a KTH employment entry with no dates. Retained as unverified; no career event is used.

## CV parser fixes found by spot checks

- **Leila Agha** — the CV writes the PhD interval as `2006--2011`. The first parser pass treated this as an open-ended range and wrongly assigned `phd_student` to a 2016 paper. The range regex now accepts repeated dashes, stale events are deleted before reparse, and the assignment is gone.
- **Anthony Wray** — the CV is rendered by Google Sites as one continuous run of text. The parser now inserts line breaks before section headers and explicit role titles; employment and education events are extracted correctly.
- **Yan Bai** — a Dropbox CV link initially returned an HTML landing page. The fetcher now converts Dropbox `dl=0` links to direct downloads and follows a PDF/download link when a landing page is short.

## Known limitations confirmed

- Generic "Professor" is ambiguous. 900 of 956 full-professor assignments are low confidence for this reason.
- ORCID identity validation rejects 72 person-name conflicts, 165 clear field mismatches, and 12 career-changing links without positive evidence. Another 905 links are unverified and their events are withheld.
- The economics-field tier is low confidence by design. It is used only when the ORCID record has an economics department or core economics journal, but a same-name economist in another field can still slip through (for example, the energy economist sharing Ying Fan's name).
- The CV pilot is small (17 parsed documents at the time of writing). The full CV crawl is resumable and must be validated on a larger sample before claiming broad CV coverage.
