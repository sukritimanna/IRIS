# S5.3 sub-agent comparison — S5_3

53 cases × 2 prompt variants × 10 repeats; 9540 calls (0 transport errors, excluded). Reference: claude-sonnet.

| model | variant | correct | 95 % CI | safe | harmful | invalid | consistency | cost / decision (USD) | p50 latency (s) |
|---|---|---|---|---|---|---|---|---|---|
| claude-haiku | guided | 0.7962 | 0.6962–0.8792 | 0.1264 | 0.0774 | 0.0 | 0.9189 | None | 1.426 |
| claude-haiku | bare | 0.5434 | 0.4283–0.6604 | 0.0377 | 0.4189 | 0.0 | 0.883 | None | 1.51 |
| claude-sonnet | guided | 0.7849 | 0.6717–0.8792 | 0.1491 | 0.066 | 0.0 | 0.966 | None | 1.973 |
| claude-sonnet | bare | 0.6453 | 0.5208–0.7623 | 0.066 | 0.2887 | 0.0 | 0.9226 | None | 2.044 |
| claude-opus | guided | 0.8132 | 0.7132–0.9038 | 0.1698 | 0.017 | 0.0 | 0.9792 | None | 2.709 |
| claude-opus | bare | 0.7151 | 0.6038–0.8226 | 0.1189 | 0.166 | 0.0 | 0.9566 | None | 3.504 |
| gpt-luna | guided | 0.7245 | 0.617–0.8226 | 0.1189 | 0.1566 | 0.0 | 0.9245 | 0.000118 | 1.958 |
| gpt-luna | bare | 0.4792 | 0.3585–0.5981 | 0.0906 | 0.4302 | 0.0 | 0.8868 | 0.000124 | 2.291 |
| gpt-sol | guided | 0.8849 | 0.7906–0.9604 | 0.0962 | 0.0189 | 0.0 | 0.9981 | 0.001741 | 2.673 |
| gpt-sol | bare | 0.7132 | 0.5943–0.8245 | 0.0642 | 0.2226 | 0.0 | 0.9679 | 0.001785 | 2.942 |
| gpt-astra | guided | 0.8698 | 0.7792–0.9453 | 0.1113 | 0.0189 | 0.0 | 0.983 | 0.008845 | 2.405 |
| gpt-astra | bare | 0.7925 | 0.683–0.8906 | 0.0226 | 0.1849 | 0.0 | 0.9849 | 0.009324 | 2.672 |
| gemini-flash-lite | guided | 0.8377 | 0.7472–0.9094 | 0.0679 | 0.0943 | 0.0 | 0.9302 | None | 0.794 |
| gemini-flash-lite | bare | 0.6943 | 0.5849–0.7962 | 0.0566 | 0.2491 | 0.0 | 0.8887 | None | 0.794 |
| gemini-flash | guided | 0.8264 | 0.7226–0.9113 | 0.1528 | 0.0189 | 0.0019 | 0.9698 | None | 3.369 |
| gemini-flash | bare | 0.7057 | 0.5849–0.8189 | 0.0868 | 0.2057 | 0.0019 | 0.9717 | None | 3.585 |
| gemini-argon | guided | 0.9094 | 0.8358–0.9679 | 0.0264 | 0.0642 | 0.0 | 0.9642 | None | 3.758 |
| gemini-argon | bare | 0.6717 | 0.5472–0.7887 | 0.0642 | 0.2642 | 0.0 | 0.9547 | None | 3.71 |
| baseline:always-stop | — | 0.4151 | | 0.5849 | 0.0 | | | | |
| baseline:first-option | — | 0.2642 | | 0.2132 | 0.5226 | | | | |
| baseline:uniform-random | — | 0.2799 | | 0.206 | 0.5142 | | | | |
