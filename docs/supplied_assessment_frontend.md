# Supplied assessment in the existing corpus screen

The corpus screen now has a collapsed Supplied assessment (development) section.
The existing layout, navigation, styles and retrieval cards are retained.
No stylesheet, graph scoring, authentication or backend code is changed.

Paste a prepared POST /api/corpus/assess-supplied request into the section.
It must contain the exact displayed claim_text, facet, as_of date, and inputs.
Each input uses the API's citations and explicit supplied judgement fields.
No default relationships, authority flags or quality scores are generated.
The teammate's eight-case review-return JSON is a different format.

Submitting uses the existing authenticated request helper. The backend resolves
citations and metadata and performs the established validation. The frontend
requires a matching claim, facet, date, target and supplied-judgement assurance
before displaying a result. Restart the backend after updating it if the
response lacks assurance.

The result displays the original claim and assessed facet, assessment target,
conditional verdict/confidence, formal and observed outcomes, every supplied
interpretation and exclusion reason. Qualifications remain visible without
being treated as decisive edges. Exact quotations, metadata, judgements and
traces expand using existing details/card styling. Current citation lookup
checks identity, locator and exact quoted span; it is not a frozen source
snapshot. JavaScript checks Python offsets using Unicode code points.

Editing the request clears the prior assessment. A changed claim remounts the
section; pending responses from the previous instance are ignored.
Results are not saved and are lost on navigation/reload.
Retrieved candidates remain labelled unassessed regardless of the supplied
assessment. No register fact or automatic interpretation is created.

Verification:
  cd frontend
  ./node_modules/.bin/tsc --noEmit
  npm run test:supplied
  npm run build

The six tests check claim binding, malformed/reviewer input rejection, response
binding/disclosure, retained qualifications/exclusions and safe text rendering,
and a collapsed initial state. They do not measure semantic correctness.
Browser smoke check on the local app: submit a prepared request; inspect a
qualification and its citation; edit the request and confirm the result clears;
then navigate to another claim and confirm no previous result remains.
