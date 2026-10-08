export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface User {
  id: number;
  email: string;
  role: "admin" | "viewer";
}

export interface AccountRef {
  id: number;
  name: string;
  display_phone_number: string;
}

export interface CaptureHealth {
  level: "ok" | "warning" | "no_data";
  reasons: string[];
  last_event_at: string | null;
  last_inbound_at: string | null;
  last_echo_at: string | null;
  inbound_7d: number;
  echoes_7d: number;
  orphan_statuses_7d: number;
  failed_events: number;
}

export interface Account {
  id: number;
  provider: string;
  provider_account_id: string | null;
  waba_id: string | null;
  phone_number_id: string | null;
  display_phone_number: string;
  name: string;
  status: "pending" | "active" | "disabled" | "error";
  has_api_key: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  contacts: number;
  conversations: number;
  active_conversations: number;
  messages: number;
  inbound_messages: number;
  outbound_messages: number;
  messages_7d: number;
  health: CaptureHealth | null;
}

export interface WebhookInfo {
  webhook_url: string;
  secret_header: string;
  registered: boolean | null;
}

export interface ContactRef {
  id: number;
  wa_id: string;
  phone: string | null;
  display_name: string;
}

export interface Contact extends ContactRef {
  name: string | null;
  saved_name: string | null;
  first_seen_at: string;
  last_activity_at: string;
  conversations: number;
  messages: number;
  accounts: AccountRef[];
}

export interface Conversation {
  id: number;
  account: AccountRef;
  contact: ContactRef;
  status: "active" | "inactive";
  started_at: string;
  last_message_at: string;
  last_inbound_at: string | null;
  last_outbound_at: string | null;
  message_count: number;
  inbound_count: number;
  outbound_count: number;
  assigned_agent: string | null;
  last_message: { type: string; text: string | null; direction: string; sent_at: string } | null;
}

export interface Media {
  id: number;
  mime_type: string | null;
  filename: string | null;
  size_bytes: number | null;
  download_status: "pending" | "downloaded" | "failed" | "skipped";
  available: boolean;
}

export interface MessageStatus {
  status: string;
  occurred_at: string;
  error_code: string | null;
  error_title: string | null;
  error_detail: string | null;
}

export interface Message {
  id: number;
  conversation_id: number;
  account_id: number;
  contact_id: number;
  provider_message_id: string;
  direction: "inbound" | "outbound";
  source: "webhook" | "echo" | "history";
  sender: string;
  recipient: string;
  type: string;
  text: string | null;
  content: Record<string, any>;
  context_message_id: string | null;
  sent_at: string;
  status: string | null;
  status_at: string | null;
  error_code: string | null;
  error_title: string | null;
  media: Media | null;
  statuses: MessageStatus[] | null;
}

export interface Overview {
  range_from: string;
  range_to: string;
  accounts: number;
  contacts: number;
  conversations: number;
  messages: number;
  active_conversations: number;
  inbound_in_range: number;
  outbound_in_range: number;
  new_contacts_in_range: number;
  conversations_in_range: number;
  by_account: { account: AccountRef; inbound: number; outbound: number; conversations: number }[];
}

export interface TimeseriesPoint {
  date: string;
  inbound: number;
  outbound: number;
  conversations: number;
  new_contacts: number;
}

export interface WebhookEvent {
  id: number;
  provider: string;
  account_id: number | null;
  source: string;
  event_kind: string | null;
  status: string;
  attempts: number;
  last_error: string | null;
  received_at: string;
  processed_at: string | null;
  next_attempt_at: string;
}

export interface OpsSummary {
  events: Record<string, number>;
  media: Record<string, number>;
  oldest_pending_event_at: string | null;
}
