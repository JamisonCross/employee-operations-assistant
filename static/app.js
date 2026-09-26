const $ = (id) => document.getElementById(id);
let token = "",
  user = null,
  handbook = [],
  requestKey = crypto.randomUUID();
function el(tag, text, cls) {
  const n = document.createElement(tag);
  n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function error(e) {
  $("error").textContent = e.message;
  $("error").classList.remove("hidden");
}
async function api(path, body) {
  const r = await fetch("/api/" + path, {
    method: body ? "POST" : "GET",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + token,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const d = await r.json();
  if (!r.ok)
    throw Error(
      typeof d.detail === "string"
        ? d.detail
        : "Check the form fields and try again.",
    );
  return d;
}
async function safe(work, button) {
  $("error").classList.add("hidden");
  if (button) button.disabled = true;
  try {
    await work();
  } catch (e) {
    error(e);
  } finally {
    if (button) button.disabled = false;
  }
}
function requestNode(r) {
  const n = el("div", "", "request");
  n.append(
    el("strong", `#${r.id} · ${r.category.toUpperCase()} · ${r.person}`),
    el("div", r.start ? `${r.start} → ${r.end}` : "Private People follow-up"),
    el("span", r.status.replaceAll("_", " "), "pill"),
    el("div", "Routing at submission: " + r.reason, "muted"),
  );
  return n;
}
async function refresh() {
  user = await api("me");
  $("available").textContent = user.balance.available + " h";
  $("reserved").textContent = user.balance.reserved + " h";
  $("total").textContent = user.balance.hours + " h";
  $("mode").textContent = user.mode;
  const requests = await api("requests");
  $("requests").replaceChildren(
    ...(requests.length
      ? requests.map(requestNode)
      : [el("p", "No requests yet.", "muted")]),
  );
  $("review-card").classList.toggle("hidden", user.role !== "reviewer");
  if (user.role === "reviewer") {
    const data = await api("review");
    $("review").replaceChildren(
      ...data.requests.map((r) => {
        const n = requestNode(r);
        if (["submitted", "escalated"].includes(r.status)) {
          const note = document.createElement("input");
          note.placeholder = "Review note (required)";
          note.setAttribute("aria-label", "Review note for request " + r.id);
          n.append(note);
          for (const decision of ["approve", "decline"]) {
            const b = el(
              "button",
              decision === "approve"
                ? r.category === "pto"
                  ? "Approve PTO"
                  : "Acknowledge follow-up"
                : "Decline",
            );
            b.disabled = r.person === user.person;
            b.onclick = () =>
              safe(async () => {
                await api("review/" + r.id, { decision, note: note.value });
                await refresh();
              }, b);
            n.append(b);
          }
        }
        return n;
      }),
    );
    $("audit").replaceChildren(
      ...data.audit.map((a) =>
        el(
          "p",
          `${a.created.slice(0, 19)} · ${a.actor} · #${a.request_id} ${a.event} · ${a.note}`,
          "muted",
        ),
      ),
    );
  }
}
async function login() {
  const d = await api("session", { person: $("identity").value });
  token = d.token;
  requestKey = crypto.randomUUID();
  $("question").value = "";
  $("review").replaceChildren();
  $("audit").replaceChildren();
  $("answer").textContent =
    "Ask a question to see a sourced answer or the next step.";
  $("sources").replaceChildren();
  $("confirmation").textContent = "";
  await refresh();
  const docs = await api("handbook");
  handbook = docs;
  $("handbook").replaceChildren(
    ...docs.map((d) => {
      const detail = document.createElement("details");
      detail.append(
        el("summary", d.title + " · " + d.version),
        el("p", d.text, "muted"),
      );
      return detail;
    }),
  );
}
$("identity").onchange = () => safe(login);
$("chat").onsubmit = (e) => {
  e.preventDefault();
  safe(async () => {
    const a = await api("chat", { question: $("question").value });
    $("answer").textContent = a.answer;
    $("sources").replaceChildren(
      el("span", a.mode, "pill"),
      ...(a.citations.length ? [el("div", "Sources used · expand to read the exact passage", "sources-heading")] : []),
      ...a.citations.map((id) => {
        const source = (a.sources || handbook).find(p => p.id === id);
        const citation = el("details", "", "citation");
        citation.append(el("summary", source ? `Handbook → ${source.title} · ${source.version}` : id));
        citation.append(el("p", source?.text || "Source passage unavailable."));
        return citation;
      }),
    );
    await refresh();
    if (a.action === "request")
      $("request-card").scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
  }, e.submitter);
};
document.querySelectorAll(".example").forEach(
  (b) =>
    (b.onclick = () => {
      $("question").value = b.dataset.q;
      $("chat").requestSubmit();
    }),
);
$("leave").addEventListener("input", () => (requestKey = crypto.randomUUID()));
$("leave").onsubmit = (e) => {
  e.preventDefault();
  safe(async () => {
    const r = await api("requests", {
      category: $("category").value,
      start: $("start").value,
      end: $("end").value,
      key: requestKey,
    });
    $("confirmation").textContent =
      `Request #${r.id}: ${r.status}. ${r.reason}`;
    await refresh();
  }, e.submitter);
};
$("people").onclick = () =>
  safe(async () => {
    const r = await api("escalations", {});
    $("sources").replaceChildren();
    $("answer").textContent =
      `People review ticket #${r.id} is open. No private details were stored.`;
    await refresh();
  }, $("people"));
const today = new Date();
const localDate = new Date(today.getTime() - today.getTimezoneOffset() * 60000)
  .toISOString()
  .slice(0, 10);
$("start").min = localDate;
$("end").min = localDate;
safe(login);
