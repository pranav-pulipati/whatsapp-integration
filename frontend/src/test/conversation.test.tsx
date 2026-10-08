/**
 * Dashboard-critical flow: a conversation opened from the inbox shows the full
 * timeline with direction, app-sent replies and delivery status.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConversationsPage } from "../pages/Conversations";

const account = { id: 1, name: "Sales — Bengaluru", display_phone_number: "15550001111" };
const contact = { id: 7, wa_id: "919876543210", phone: "+919876543210", display_name: "Priya Sharma" };
const conversation = {
  id: 3,
  account,
  contact,
  status: "active",
  started_at: "2026-10-08T09:00:00Z",
  last_message_at: "2026-10-08T09:05:00Z",
  last_inbound_at: "2026-10-08T09:00:00Z",
  last_outbound_at: "2026-10-08T09:05:00Z",
  message_count: 2,
  inbound_count: 1,
  outbound_count: 1,
  assigned_agent: null,
  last_message: { type: "text", text: "Yes it is!", direction: "outbound", sent_at: "2026-10-08T09:05:00Z" },
};
const base = {
  conversation_id: 3,
  account_id: 1,
  contact_id: 7,
  content: {},
  context_message_id: null,
  status_at: null,
  error_code: null,
  error_title: null,
  media: null,
  statuses: [],
};
const messages = [
  // API returns newest first (order=desc); the UI must show oldest first.
  { ...base, id: 2, provider_message_id: "wamid.2", direction: "outbound", source: "echo", sender: "15550001111", recipient: "919876543210", type: "text", text: "Yes it is!", sent_at: "2026-10-08T09:05:00Z", status: "read" },
  { ...base, id: 1, provider_message_id: "wamid.1", direction: "inbound", source: "webhook", sender: "919876543210", recipient: "15550001111", type: "text", text: "Is the 2BHK available?", sent_at: "2026-10-08T09:00:00Z", status: "received" },
];

function respond(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
}

beforeEach(() => {
  Element.prototype.scrollTo = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const path = new URL(url, "http://x").pathname;
      if (path === "/api/v1/accounts") return respond([]);
      if (path === "/api/v1/conversations") return respond({ items: [conversation], total: 1, limit: 30, offset: 0 });
      if (path === "/api/v1/conversations/3") return respond(conversation);
      if (path === "/api/v1/conversations/3/messages") return respond({ items: messages, total: 2, limit: 100, offset: 0 });
      return Promise.resolve(new Response("{}", { status: 404 }));
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Conversation detail", () => {
  it("renders the timeline oldest-first with direction and read status", async () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={["/conversations/3"]}>
          <Routes>
            <Route path="/conversations/:id" element={<ConversationsPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Is the 2BHK available?")).toBeTruthy();
    const bubbles = container.querySelectorAll(".timeline .msg");
    expect(bubbles).toHaveLength(2);
    expect(bubbles[0].className).toContain("in");
    expect(bubbles[1].className).toContain("out");
    expect(within(bubbles[1] as HTMLElement).getByTitle("Read")).toBeTruthy();
    expect((bubbles[1].querySelector(".bubble") as HTMLElement).title).toContain("WhatsApp Business App");

    const header = container.querySelector(".thread-head") as HTMLElement;
    expect(within(header).getByText("Priya Sharma")).toBeTruthy();
    expect(header.textContent).toContain("Sales — Bengaluru");
    expect(header.textContent).toContain("+91 98765 43210");
  });
});
