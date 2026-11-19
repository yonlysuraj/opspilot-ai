# Portfolio demo walkthrough

Start with fresh demo data from the [README setup](../README.md#quick-start). The sample runbooks are synthetic and ship with the repository. The walkthrough uses both the chat model and the embedding model.

| View | Try it | Verify |
| --- | --- | --- |
| **Knowledge Base** | Upload both TXT files in `data/sample_documents/` and search for `staging rollback test credentials`. | Both documents are indexed. The payment runbook appears in the search results with a line reference. |
| **Agent Workspace** | Choose **Review blockers with sources** and send the prompt. | Three overdue tasks appear. `PAY-104` and `PLAT-201` have cited blockers. Open the two saved drafts and check the recipients. |
| **Workflow Trace** | Use **View trace** under the answer. | Seven MCP steps show their persisted IDs, statuses, and durations. Reload the conversation to see the same drafts and citations. |
| **Approval Center** | In a new conversation, send `Change PAY-109 to in progress.` Open the proposal and approve it with the configured token. | The proposal shows `open` to `in progress` before approval. The run resumes and its history records the approved change. |
| **Overview** | Return after the workflows finish. | The completed runs appear in Recent activity. Pending approvals appear in the count while a proposal is waiting. |

To demonstrate rejection, open a new conversation, send `Change PLAT-201 to done.`, then reject the proposal. Check the conversation for the rejection and use `What are the details of PLAT-201?` to verify the task remains open. Each example assumes a fresh seed. After an approval changes a task, choose a different valid status if you repeat that example.

## Presenter prompts

- `Show my overdue tasks, identify the highest-priority blockers, cite related documents, and draft follow-ups for the responsible people.`
- `What is the status of the Payments Migration project?`
- `Search the knowledge base for staging rollback test credentials.`
- `Change PAY-109 to in progress.`
- `Change PLAT-201 to done.`

The dashboard intentionally identifies the local demo requester as Maya Chen. Approval decisions are separate from drafting, and drafts remain unsent. [Architecture and boundaries](architecture.md)
