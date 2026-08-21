# MOX-ADV P0 for GPT Sites

Private GPT Sites production candidate for the first MOX-ADV campaign workflow.

The Site reads the connected Yandex Direct account and Yandex Metrika goal through server-side production credentials, researches a user-selected first-party HTTPS site, and persists revisioned state in D1. The Model step emits a versioned analytics evidence snapshot with primary-source lineage, a confidence vector, explicit coverage gaps, and an unavailable pre-launch cost whenever no comparable first-party history exists; it never invents competitor or Wordstat evidence. The resulting business model prepares a reviewable Campaign Strategy and exact Campaign Draft. After one exact Human Decision Gate it creates the real Direct object graph through v501, confirms the campaign is non-serving (`State=OFF` for a draft or `SUSPENDED` for a suspendable campaign), submits the ad for moderation, and repeats the non-serving readback. `Campaigns.resume` is not implemented.
