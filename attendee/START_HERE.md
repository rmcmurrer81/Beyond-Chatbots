# Start here — attendee guide

**Beyond Chatbots · October 10, 2026 · Robert McMurrer / Kira Labs**  
Prepared October 8; updated October 9. This guide uses the public presentation's version 14 evidence cutoff: **October 9, 15:59 UTC**.

## Ten minutes after the talk

| Time | Read | What to take away |
| --- | --- | --- |
| 0–2 minutes | [Project overview](../README.md) and [latest speaking update](../presentation/Latest-Speaking-Update.txt) | The question is how to test memory, identity boundaries and continuity in local AI. |
| 2–5 minutes | [Reviewed results](../presentation/Reviewed-Results.txt) | Read a successful narrow result alongside a failed result and its limitations. |
| 5–7 minutes | [Architecture map and glossary](ARCHITECTURE_AND_GLOSSARY.md) | NewBrain, Aster, Avatar Builder, KiraWorld and personal state have different roles. |
| 7–9 minutes | [Generic demo status](GENERIC_DEMO.md) and [recording status](DEMO_RECORDING.md) | Historical reviewed output exists; a runnable public demo and its recording are pending. |
| 9–10 minutes | [Help test](HELP_TEST.md) and [reuse policy](REUSE_POLICY.md) | Choose a bounded review check and understand what the current release permits. |

For a visual overview, use the [slide PDF](../presentation/Beyond-Chatbots-Slides.pdf). For answers to common questions, read the [very short Q&A](../presentation/Very-Short-QA.md). The fuller [audience Q&A](../presentation/Audience-Questions.txt) explains the experiment boundaries.

## What the evidence currently supports

The public summary reports four accepted migration reviews and **three of four** independently verified delayed NewBrain restart results. According to that summary, each accepted restart preserved all **10,720 history records**, checked **64 comparison pairs and 256 generation steps** plus six out-of-vocabulary pairs, and added no training updates. The remaining restart is pending. These are reported saved-output review results; this guide does not independently verify private raw evidence. This is preservation evidence within those tests; it does not establish reliable general memory or conversation.

The small command learner retained its exposed task with review across five seeds. The visual learner failed to generalize, and Aster's saved-memory study failed its overall reliability criterion. The results page retains these failures. A completed integrated companion, subjective experience, general superiority to Qwen and clinical benefit are not established.

## Downloads and availability

Use **Code → Download ZIP** on the [repository page](https://github.com/rmcmurrer81/Beyond-Chatbots), then extract it. Presentation documents can be read offline. The large PowerPoint and slide PDF may need downloading rather than GitHub preview.

At this guide's preparation, this repository contains presentation and attendee documents. NewBrain, Avatar Builder and Aster implementation copies are awaiting their separate reviewed release. The original NewBrain and KiraWorld repositories and private identity/state remain private. Do not treat planned paths, narrated examples or saved summaries as a runnable software package.

Read the [**AI History and NewBrain book**](AI-History-and-NewBrain.pdf), the current **42-page** illustrated companion to the talk. It covers Turing, early AI pioneers, ELIZA and the ELIZA effect, expert systems, robotics, machine learning, generative AI, and NewBrain. The actual ELIZA screenshot is from a **2023 reimplementation**, not an original 1966 photograph. See its [SHA-256 checksum](AI-History-and-NewBrain.pdf.sha256), [historical and image sources](AI_HISTORY_VISUAL_SOURCES.md), and [full contents](AI_HISTORY_EXPANDED_CONTENTS.md).

[Attendee checksums](SHA256SUMS.txt) cover the six attendee Markdown guides; [presentation checksums](../SHA256SUMS.txt) cover their listed files. These lists do not authenticate future software releases.

## The author's reflection

On **page 34**, *Can a machine become someone?* discusses the question behind Maya and NewBrain, beginning with Daniel Graystone's remark to Joseph Adama in the *Caprica* pilot. The scene's context is explained for readers who have never seen the show. The chapter distinguishes emotion, moral conscience and subjective consciousness; it does not claim that Maya has demonstrated them.

[Read the editable reflection](AUTHORS_REFLECTION.md). The book is maintained at **one stable PDF filename** so attendees do not have to guess which copy is current.
