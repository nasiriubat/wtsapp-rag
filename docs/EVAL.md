# Eval

Numbers from `app/scripts/eval.py` on the sets in `evals/`. Every row is a real
run: the messages go through the same chunking, retrieval and answering as the
product, and a second provider grades the answers.

- **Answer accuracy**: a judge model compares the answer with the reference.
- **Citation accuracy**: the message the bot quoted is one the set marks as
  evidence for that question.
- **Abstention**: share of unanswerable questions the bot refused.
- **False refusal**: share of answerable questions it refused.
- **p50/p95**: end to end, including retrieval, the local reranker and the
  provider call, on one laptop CPU.
- **Cost/question**: provider spend for the run divided by questions, at the
  prices configured for that provider.

Reproduce a row with:

```
docker compose exec -T app python scripts/eval.py evals/cabin.jsonl \
  --provider <answering provider id> --judge <judge provider id>
```

## Sets

- **cabin** (12 questions, 15 messages, English and Finnish). Hand written for
  this project: recall, a decision that changes twice, a cross-lingual pair
  where the question and the source are in different languages, a fact split
  across sessions, and three questions the chat cannot answer.

## Results

| Run | Set | Answering model | Judge | Questions | Answer accuracy | Citation accuracy | Abstention | False refusal | p50 | p95 | Cost/question |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-05 | cabin | gpt-5.4-mini | claude-opus-5 | 12 | 100% | 67% | 100% | 0% | 1668 ms | 2185 ms | €0.00033 |
| 2026-09-04 | cabin | claude-opus-5 | gpt-5.4-mini | 12 | 100% | 56% | 100% | 0% | 3448 ms | 4245 ms | €0.00744 |
| 2026-09-04 | cabin | gpt-5.4-mini | claude-opus-5 | 12 | 56% | 60% | 100% | 44% | 1644 ms | 2761 ms | €0.00014 |

The first row is the shipped defaults, on the released code. The second is the
same set answered by a much larger model: the same accuracy for twenty times
the cost and twice the latency, which is the argument for a small model here.
The third is the shipped code with `confidence_threshold` forced back to 0.1,
kept as the evidence for the change below.

Citation accuracy moves a few points between runs because the answer's wording
decides which message is quoted; treat single-digit differences as noise.

## What these runs changed

**The confidence threshold now defaults to 0.** It used to be 0.1, compared
against the reranker's score. That refused 44% of answerable questions. The
reranker's scores are not comparable across languages: a Finnish question whose
correct chunk was ranked first scored 0.0008, while an unanswerable question
scored 0.0009. No threshold separates those. Letting every question reach the
model, which is told to reply `NO_ANSWER` when the excerpts do not answer, gives
100% abstention on the unanswerable questions and no false refusals. The setting
remains for operators who would rather save provider calls than answer
everything.

**The bot quotes the message the answer came from, not the first message of the
episode.** Citation accuracy went from 20% to 56-67% with that change alone.

**The harness caught its own bug.** Re-running the eval after the release work
showed 44% accuracy again: `scripts/eval.py` still forced a threshold of 0.1 of
its own, so it was measuring a gate the product no longer ships. Without
`--threshold` it now creates the group a real operator would get. Re-run the
eval after changing a default, not only after changing the code.

## Load

`app/scripts/loadtest.py`, one laptop, everything in Docker on the same host,
`gpt-5.4-mini` answering:

| What | Result |
|---|---|
| Ingest 500 messages (a busy group's day) | p50 6 ms, p95 7 ms |
| Chunk those 500 messages into 34 chunks | 1.1 s |
| 30 questions at concurrency 4 | p50 4.45 s, p95 4.85 s, max 4.95 s, 0 failed |

Ingest is far inside the one-second target. A single question answers in about
1.6 s; four at once push p95 to 4.85 s, which is at the edge of the five-second
target. The local reranker is the bottleneck: it is CPU-bound and the answers
queue behind each other. A group that asks four questions in the same second is
already unusual, but this is the number to watch when tuning
`retrieval.RERANK`.

## What these runs did not settle

- **Citation accuracy is the weakest number.** 56% means that in nearly half of
  answered questions the quoted message is in the right conversation but is not
  the message the set marks as evidence. Picking the message by word overlap
  with the answer is a cheap heuristic; the next step is to ask the model which
  message it used.
- **One hand-written set is not a benchmark.** The public multi-party memory
  sets (EverMemBench, SocialMemBench) need a loader that maps their transcripts
  into this format. Until that lands, treat these numbers as a regression test
  for this project, not as a comparison with other systems.
- **Cost and latency are laptop numbers**, one question at a time, with the
  reranker on CPU. The load test in `app/scripts/loadtest.py` measures the
  concurrent case.
