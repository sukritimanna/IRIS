Eligibility conditions on the recovery menus (frozen prompts, menus filtered by error code).
`*_run1.csv`: the run as made (first conditions, with flag_and_continue admissible for SCF_LIMITED; 16 cases decided
by code). The condition was then corrected to WALLTIME and NELM only (see eval_extra/eligibility.py, Disclosure),
which makes C22 the 17th code-decided case; `python -m eval_extra.eligibility --summarize` re-scores the saved calls
under the current conditions (C22's old calls are not scored). Paper numbers: 2,385 decisions, 1,620 reaching a
model; correct 85.3-97.0% per model (90.4% pooled); harmful 4/2,385 (0.17%), all the R5 judgment call.
