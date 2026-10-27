# Public footage audit

Reviewed on 2026-10-27. The available material supports **one provisional
conversation**. Its 70-second learning excerpt
and 30-second returning excerpt total 100 seconds of scored footage. The return
is another passage of the same conversation, not a second independent scenario.

## Sources considered

| Source | Access and suitability | Decision |
| --- | --- | --- |
| [Ego4D](https://ego4d-data.org/docs/start-here/) | Access to videos and annotations requires an approved license agreement and emailed credentials; the documentation estimates about 48 hours. | Excluded from this no-account pilot. It remains a possible later dataset, not an exhausted source. |
| [EgoCom](https://github.com/facebookresearch/EgoCom-Dataset) | Public release with first-person audio/video and transcripts. Its documented conversations contain three participants, usually two visible from a participant's camera. Local metadata also records three speakers. | Excluded from the initial one-on-one benchmark. Useful later for background-speaker and multiple-face stress tests. |
| [CoMind](https://comind.ethz.ch/) | Publicly downloadable paired head-mounted recordings of collaborative activities. | One cooking passage prepared. Inspected candidate transcripts and contact sheets have sparse personal information and intermittent or oblique faces. This does not establish that the full dataset lacks suitable conversations. |

No synthetic media or gated dataset was substituted to reach the target count.
Additional independent conversations and recordings on different days remain useful
future dataset work; they are not a completion gate in the current runners.

## Attribution and terms

CoMind footage is credited to **Alexey Gavryushin, Dingxi Zhang, Zhao Huang,
Alexandros Delitzas, Jiaqi Chen, Ben Ellis, Cedric Zöllner, Manthan Patel,
Manuel Kaufmann, Marc Pollefeys, and Xi Wang**, *CoMind: Understanding
Collaborative Human Activity from Multiple Minds and Views*, ECCV 2026.
The publisher's rendered [license section](https://comind.ethz.ch/#license)
specifies [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Excerpts were trimmed, resized, and re-encoded; no synthetic audio/video was
added. An older CC BY-NC label exists inside an HTML comment, not the rendered
license section.

The recording identifier is `571b195e-95dc-4686-a355-0b26a6ece873`.
The [source video](https://comind.ethz.ch/dataset/571b195e-95dc-4686-a355-0b26a6ece873/mp4s/leader_trimmed_sync.mp4)
is the leader's first-person view; the helper is the expected visitor.
[Publisher file hashes](https://comind.ethz.ch/dataset/571b195e-95dc-4686-a355-0b26a6ece873/healthcheck.json)
and the [publisher download script](https://comind.ethz.ch/scripts/comind_download.py)
provide provenance. The full source file was not downloaded and its publisher
hash was not independently checked. All five local excerpt hashes were checked
against the frozen manifest.

## Frozen pilot and preparation

Media, source transcripts, publisher metadata, and original annotations are retained
under `backend/.local/benchmark-inputs/public/`, outside Git. Current
`audio.json`, `face.json`, and `video.json` manifests in the parent input directory
retain exact filenames, original source intervals, checksums, preparation commands
and the same provisional labels. Historical reports and benchmark implementations
were deleted during the four-path rewrite.

| Use | Original source seconds | Duration |
| --- | --- | --- |
| Enrollment 1 | 3–11 | 8 s |
| Enrollment 2 | 574.5–582.5 | 8 s |
| Enrollment 3 | 968.7–976.7 | 8 s |
| Learning | 165–235 | 70 s |
| Returning excerpt | 235–265 | 30 s |

Enrollment intervals are disjoint from both scored passages. All samples use the
same recording, which makes voice enrollment and recall easier than recordings
on separate days. Enrollment passages were selected from source subtitles,
without inspecting Remind predictions. Their solo-speaker suitability remains
provisional until someone listens to them.

For example, the learning excerpt was prepared with the following command from
the frozen manifest; the other four commands are recorded there in full:

```bash
ffmpeg -ss 165 -i https://comind.ethz.ch/dataset/571b195e-95dc-4686-a355-0b26a6ece873/mp4s/leader_trimmed_sync.mp4 -t 70 -map 0:v:0 -map 0:a:0 -vf scale=640:-2 -c:v libx264 -preset veryfast -crf 23 -c:a aac comind_571_leader_165_235.mp4
```

Encoder versions can affect output bytes. Record a new media checksum and freeze
a new dataset artifact if recreating excerpts produces different bytes; do not
silently replace a frozen file or adjust expectations after seeing predictions.
See [the runner guide](README.md#run) for the
backend replay commands.

## Annotation limits and coverage

Labels were prepared before Remind inference using the publisher's automated
leader/helper subtitle files and independent visual inspection of contact
sheets. **No auditory verification was possible in this execution environment.**
Those subtitle files disagree on some speaker labels and phrase boundaries.
Ambiguous turns are marked uncertain; boundaries may be inaccurate by roughly
one to two seconds. Visibility was conservatively sampled at two frames per
second for learning and one for return. Unlabelled boundary gaps do not enter
identity scoring. These annotations are independent of Remind output, but are
not human-audited ground truth; all annotation-dependent scores are provisional.

The only frozen positive personal claim is that the helper is a computer
scientist. Its statement occurs approximately 23.53–24.53 seconds into the
learning excerpt while their face is out of view. It remains in useful-fact
coverage to expose the effect of the face gate. An unmatched equivalent
predicate requires separate adjudication; it must not change the frozen raw
score.

This passage cannot measure names, ages, relationships, relatives, corrections,
plans, contradictions, or broad useful-fact coverage. A successful replay would
establish integrated execution for this sample, not real-world accuracy or a
population accuracy measurement. It also cannot establish physical microphone
quality, natural camera capture quality, or usability for the intended users.
