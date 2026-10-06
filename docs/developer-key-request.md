# Requesting a Canvas developer key

A student cannot self-issue an institutional Canvas OAuth developer key. A root-account administrator approves the app and issues/enables its developer key. Personal access tokens are suitable for your own testing; Canvas's policy does not permit distributing a multi-user application that asks people to supply manually generated tokens.

For U of T Quercus, start with the [Centre for Teaching Support & Innovation's educational technology support](https://teaching.utoronto.ca/edtech/) at **q.help@utoronto.ca**. Ask for the Quercus API integration/developer-key approval process; approval is discretionary. A commercial/global integration may require Instructure review, and institutions still control whether a global key is enabled.

Prepare a real HTTPS deployment, exact callback URL, repository, privacy policy, support contact, read-only endpoint scope list, user-consent/disconnect flow, data storage/retention description, and a test plan. There is no guarantee the institution will approve a student project.

## Draft request — not sent

Subject: Quercus API OAuth developer-key approval for a read-only student companion

Hello Quercus Support,

I'm Mahimn Patel, a U of T student developing Course Companion for Canvas, a read-only MCP integration that lets a student retrieve their own course information in ChatGPT. Could you advise me on the approval process for a scoped Canvas OAuth developer key, and who reviews student-developed integrations?

The source is at https://github.com/mahimn01/canvas-chatgpt-plugin. The tool catalog reads courses, assignments, announcements, modules, course pages/files, calendar/planner, the student's grades, and inbox messages. It cannot submit work, send messages, or change grades. Inbox reads do not mark messages read. Public users would authorize through Quercus OAuth, with encrypted per-user grants and disconnect/revocation support.

I can provide the exact GET scope list, a test deployment and callback URL, privacy and retention details, and a demonstration before any public launch. Please let me know the required review steps and whether this use case is eligible.

Thank you,
Mahimn Patel

References: [Canvas OAuth policy](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth), [developer keys](https://developerdocs.instructure.com/services/canvas/oauth2/file.developer_keys).
