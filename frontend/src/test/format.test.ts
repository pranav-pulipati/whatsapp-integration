import { describe, expect, it } from "vitest";
import { formatPhone, initials, messagePreview, plural, timeAgo } from "../lib/format";

describe("format helpers", () => {
  it("groups Indian and NANP numbers, leaves others plain", () => {
    expect(formatPhone("919876543210")).toBe("+91 98765 43210");
    expect(formatPhone("15550001111")).toBe("+1 555 000 1111");
    expect(formatPhone("5511999998888")).toBe("+5511999998888");
    expect(formatPhone(null)).toBe("—");
  });

  it("builds initials from names, '#' for numbers", () => {
    expect(initials("Priya Sharma")).toBe("PS");
    expect(initials("João")).toBe("J");
    expect(initials("+91 98765")).toBe("#");
  });

  it("previews non-text messages with a type label", () => {
    expect(messagePreview({ type: "text", text: "Hi" })).toBe("Hi");
    expect(messagePreview({ type: "image", text: "Floor plan" })).toBe("Photo · Floor plan");
    expect(messagePreview({ type: "audio", text: null })).toBe("Voice message");
  });

  it("pluralises and formats relative time", () => {
    expect(plural(1, "message")).toBe("1 message");
    expect(plural(3, "message")).toBe("3 messages");
    const now = Date.parse("2026-10-08T12:00:00Z");
    expect(timeAgo("2026-10-08T11:30:00Z", now)).toBe("30m ago");
    expect(timeAgo("2026-10-08T07:00:00Z", now)).toBe("5h ago");
    expect(timeAgo(null, now)).toBe("never");
  });
});
