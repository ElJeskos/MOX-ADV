# MOX-ADV P0 for GPT Sites

Private GPT Sites production candidate for the first MOX-ADV campaign workflow.

The Site reads the connected Yandex Direct account and Yandex Metrika goal through server-side production credentials, researches a user-selected first-party HTTPS site, persists revisioned state in D1, and prepares a reviewable Campaign Strategy and exact Campaign Draft. After one exact Human Decision Gate it creates the real Direct object graph through v501, immediately suspends and reads back the campaign, submits the ad for moderation, and confirms that delivery and spend remain off. `Campaigns.resume` is not implemented.
