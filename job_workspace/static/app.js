"use strict";

const stages = {
  planning: "Планирование",
  awaiting_plan: "Согласование",
  implementation: "В работе",
  paused: "На паузе",
  review: "На ревью",
  done: "Завершена",
};
const steps = ["Планирование", "Согласование", "Реализация", "Ревью", "Готово"];
const stageIndex = { planning: 0, awaiting_plan: 1, implementation: 2, paused: 2, review: 3, done: 4 };
const roles = { planner: "Планировщик", coder: "Исполнитель", reviewer: "Ревьюер", owner: "Владелец задачи" };
const effects = { publish: "Публикация", access: "Изменение доступа", delete: "Удаление данных", external: "Внешнее действие" };
const paths = {
  logo: "M3 4h7v7H3zM14 4h7v7h-7zM3 15h7v5H3zM14 17.5l2 2 5-5",
  board: "M4 4h16v16H4zM4 10h16M10 10v10",
  clock: "M12 5v7l4 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  help: "M9.5 9a2.5 2.5 0 1 1 3.4 2.3c-.6.3-.9.8-.9 1.7M12 16.5h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  plus: "M12 5v14M5 12h14",
  next: "m9 6 6 6-6 6",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  check: "m5 12 4 4L19 6",
  pause: "M9 6v12m6-12v12",
  pencil: "M4 20l1-5L16 4l4 4L9 19 4 20Zm10-14 4 4",
  x: "m6 6 12 12M18 6 6 18",
  folder: "M3 6h7l2 2h9v11H3z",
  file: "M6 3h8l4 4v14H6zm8 0v5h4M9 13h6m-6 4h6",
};

const app = document.querySelector("#app");
const dialog = document.querySelector("#dialog");
const notice = document.querySelector("#notice");
const state = { jobs: [], route: null, record: null, events: [], tab: "plan", filter: "all", query: "" };
let requestNumber = 0;
let noticeTimer;
const dayFormat = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });
const timeFormat = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });

function element(tag, attrs = {}, ...children) {
  const result = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on")) result.addEventListener(key.slice(2), value);
    else result.setAttribute(key, value === true ? "" : String(value));
  }
  for (const item of children.flat(Infinity)) {
    if (item !== null && item !== undefined && item !== false) result.append(item instanceof Node ? item : String(item));
  }
  return result;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(svg.namespaceURI, "path");
  path.setAttribute("d", paths[name]);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "1.7");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.append(path);
  return svg;
}

function button(label, action, { variant = "", symbol, iconOnly = false, type = "button" } = {}) {
  return element("button", {
    type, class: ("button " + variant + (iconOnly ? " icon-button" : "")).trim(),
    onclick: action, "aria-label": iconOnly ? label : null, title: iconOnly ? label : null,
  }, symbol && icon(symbol), iconOnly ? null : label);
}

function dot(className = "") {
  return element("span", { class: ("dot " + className).trim(), "aria-hidden": "true" });
}

function status(stage) {
  return element("span", { class: "status tone-" + stage }, dot(), stages[stage]);
}

function showNotice(message) {
  window.clearTimeout(noticeTimer);
  notice.textContent = message;
  notice.hidden = false;
  noticeTimer = window.setTimeout(() => { notice.hidden = true; }, 4000);
}

function when(timestamp, className = "quiet") {
  const date = new Date(timestamp);
  const day = date.toDateString() === new Date().toDateString() ? "Сегодня" : dayFormat.format(date);
  return element("time", { datetime: timestamp, class: className }, day + ", " + timeFormat.format(date));
}

async function api(path, payload) {
  const options = payload && {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  };
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("Связь с приложением прервалась. Повторите попытку.");
  }
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(body.error || "Запрос завершился ошибкой.");
    error.code = body.code;
    throw error;
  }
  return body;
}

function parseRoute() {
  const hash = location.hash.slice(1);
  const job = /^job\/([1-9][0-9]{0,17})$/.exec(hash);
  if (job && Number.isSafeInteger(Number(job[1]))) return { view: "job", id: Number(job[1]) };
  const activity = /^activity(?:\/([1-9][0-9]{0,17}))?$/.exec(hash);
  if (activity) return { view: "activity", id: activity[1] ? Number(activity[1]) : null };
  return hash ? { view: "jobs" } : null;
}

async function refresh() {
  const request = ++requestNumber;
  try {
    const { jobs } = await api("/api/jobs");
    if (request !== requestNumber) return;
    let route = parseRoute();
    if (!route) {
      route = jobs.length ? { view: "job", id: jobs[0].id } : { view: "jobs" };
      history.replaceState(null, "", route.view === "job" ? "#job/" + route.id : "#jobs");
    }
    if (route.id && !jobs.some((job) => job.id === route.id)) {
      history.replaceState(null, "", "#jobs");
      route = { view: "jobs" };
      showNotice("Задача недоступна.");
    }
    let record = null;
    let events = [];
    if (route.view === "job") {
      record = await api("/api/jobs/" + route.id);
    } else if (route.view === "activity") {
      ({ events } = await api("/api/activity"));
    }
    if (request !== requestNumber) return;
    if (state.route?.view !== route.view || state.route?.id !== route.id) state.tab = "plan";
    Object.assign(state, { jobs, route, record, events });
    render();
  } catch (error) {
    if (request !== requestNumber) return;
    if (state.route) showNotice(error.message);
    else app.replaceChildren(element("main", { class: "page blank" },
      element("h1", {}, "Рабочее пространство недоступно"),
      element("p", { class: "muted" }, error.message),
      button("Повторить", refresh)));
  }
}

function sidebar() {
  const { route, jobs } = state;
  function link(label, symbol, target, current) {
    return element("a", {
      href: target, class: "side-link" + (current ? " is-current" : ""), "aria-current": current ? "page" : null,
    }, icon(symbol), label);
  }
  return element("aside", { class: "sidebar" },
    element("a", { class: "brand", href: "#jobs" }, element("span", { class: "brand-mark" }, icon("logo")), "Job Workspace"),
    element("nav", { class: "side-nav", "aria-label": "Рабочее пространство" },
      link("Обзор", "board", "#jobs", route.view === "jobs"),
      link("Журнал", "clock", "#activity", route.view === "activity")),
    element("div", { class: "side-heading" }, "Задачи", element("span", { class: "count" }, jobs.length)),
    element("nav", { class: "side-jobs", "aria-label": "Последние задачи" },
      jobs.slice(0, 8).map((job) => {
        const current = route.view === "job" && route.id === job.id;
        return element("a", {
          href: "#job/" + job.id, class: "job-link" + (current ? " is-current" : ""),
          title: job.title + " · " + stages[job.stage], "aria-current": current ? "page" : null,
        }, dot("tone-" + job.stage), element("span", { class: "job-name" }, job.title));
      })),
    element("div", { class: "side-footer" },
      element("button", { class: "side-link", type: "button", onclick: showHelp }, icon("help"), "Как это работает")));
}

function render() {
  const job = state.record?.job;
  const crumb = job ? job.code : state.route.view === "activity" ? "Журнал" : "Обзор";
  const page = job ? jobPage(state.record) : state.route.view === "activity" ? activityPage() : overviewPage();
  app.replaceChildren(element("div", { class: "shell" }, sidebar(),
    element("div", { class: "workspace" },
      element("header", { class: "topbar" },
        element("nav", { class: "breadcrumbs", "aria-label": "Текущий раздел" },
          element("a", { href: "#jobs" }, "Задачи"), icon("next"), element("span", { class: "current" }, crumb)),
        button("Новая задача", createJob, { symbol: "plus" })),
      page)));
  document.title = job ? job.title + " · Job Workspace" : "Job Workspace";
}

function progress(stage) {
  const current = stageIndex[stage];
  return element("ol", { class: "progress", "aria-label": "Этапы задачи" }, steps.map((label, index) => {
    const complete = index < current || stage === "done";
    const active = index === current && stage !== "done";
    const style = complete ? "is-complete" : active ? "is-active" : null;
    const glyph = complete ? icon("check") : active ? dot() : null;
    return element("li", { class: style, "aria-current": active ? "step" : null },
      element("span", { class: "step-icon", "aria-hidden": "true" }, glyph), label);
  }));
}

function callout(symbol, title, description, actions = [], variant = "") {
  return element("section", { class: ("callout " + variant).trim() },
    element("span", { class: "callout-icon" }, icon(symbol)),
    element("div", {}, element("h2", {}, title), description && element("p", {}, description)),
    actions.length ? element("div", { class: "button-row" }, actions) : null);
}

function currentAction(job) {
  if (job.stage === "paused") {
    const request = job.effects.at(-1);
    if (!request.decision) {
      return callout("pause", "Ожидается одобрение действия",
        effects[request.kind] + " · " + request.target,
        [button("Рассмотреть запрос", () => decideEffect(job, request), { symbol: "arrow" })], "pending");
    }
    const decision = request.decision.value === "approve" ? "Действие одобрено" : "Действие отклонено";
    return callout("check", decision, request.decision.note || request.target,
      [button("Продолжить работу", () => resumeJob(job, request), { symbol: "arrow" })]);
  }
  if (job.stage === "implementation") {
    return callout("file", "Работа по согласованному плану", "Добавьте результат и материалы, когда они будут готовы к проверке.", [
      button("Запросить одобрение", () => requestEffect(job), { variant: "secondary" }),
      button("Передать на ревью", () => submitReview(job)),
    ]);
  }
  if (job.stage === "review") {
    return callout("file", "Результат на ревью", "Ревьюер может принять результат или вернуть его с замечаниями.",
      [button("Открыть результат", () => setTab("results"), { symbol: "arrow" })]);
  }
  if (job.stage === "done") {
    return callout("check", "Результат принят", job.reviews.at(-1).note,
      [button("Открыть результат", () => setTab("results"), { variant: "secondary" })], "complete");
  }
  return null;
}

function avatar(name, role) {
  const words = name.trim().split(/\s+/);
  const letters = words.length > 1 ? words.slice(0, 2).map((word) => Array.from(word)[0]).join("") : Array.from(words[0]).slice(0, 2).join("");
  return element("span", { class: "avatar " + role, "aria-hidden": "true" }, letters.toUpperCase());
}

function person(name, role, extra = null) {
  return element("div", { class: "team-person" }, avatar(name, role),
    element("div", {}, element("span", { class: "person-name" }, name),
      element("span", { class: "person-role" }, roles[role])),
    extra);
}

function teamCard(job) {
  return element("section", { class: "panel padded" },
    element("header", { class: "panel-header" }, element("h2", {}, "Роли"),
      job.stage !== "done" && button("Изменить роли", () => editTeam(job), { variant: "ghost", symbol: "pencil", iconOnly: true })),
    element("ul", { class: "team-list" }, Object.entries(job.team).map(([role, name]) =>
      element("li", {}, person(name, role)))));
}

function timeline(job, events) {
  return element("section", { class: "panel padded" }, element("header", { class: "panel-header" }, element("h2", {}, "Последние события")),
    element("ol", { class: "timeline" }, events.slice(0, 4).map((entry) => element("li", {}, dot(entry.kind),
      element("div", {}, element("p", {}, entry.title), when(entry.at))))),
    element("a", { class: "text-link activity-link", href: "#activity/" + job.id }, "Весь журнал", icon("arrow")));
}

function setTab(tab) {
  state.tab = tab;
  const oldPage = document.querySelector(".job-panel");
  if (oldPage && state.record) {
    oldPage.replaceWith(jobPanel(state.record.job));
    document.querySelector('.tab[aria-pressed="true"]').focus();
  }
}

function jobPage({ job, events }) {
  return element("main", { class: "page" },
    element("header", { class: "page-heading" },
      element("div", { class: "job-meta" }, element("span", { class: "job-code" }, job.code), status(job.stage)),
      element("h1", {}, job.title), element("p", { class: "page-intro multiline" }, job.brief)),
    progress(job.stage), currentAction(job),
    element("div", { class: "columns" }, jobPanel(job),
      element("aside", { class: "side-stack", "aria-label": "Участники и события" }, teamCard(job), timeline(job, events))));
}

function jobPanel(job) {
  const tabs = [["plan", "План"], ["comments", "Обсуждение", job.comments.length], ["results", "Результаты", job.submissions.length]];
  const views = { plan: planPanel, comments: commentsPanel, results: resultsPanel };
  return element("section", { class: "panel job-panel" },
    element("div", { class: "tab-row", "aria-label": "Раздел задачи", role: "group" },
      tabs.map(([key, label, count]) => element("button", {
        type: "button", class: "tab", "aria-pressed": String(state.tab === key), onclick: () => setTab(key),
      }, label, count > 0 ? element("span", { class: "tab-count" }, count) : null))),
    element("div", { class: "panel-body" }, views[state.tab](job)));
}

function list(values, renderValue = (value) => value) {
  return element("ul", { class: "line-list body-copy" }, values.map((value) => element("li", {}, renderValue(value))));
}

function section(title, content) {
  return element("div", { class: "section" }, element("h3", {}, title), content);
}

function currentVersion(hash, version) {
  return element("span", { class: "chip short-hash", title: hash }, "v" + version + " · " + hash.slice(0, 8));
}

function planPanel(job) {
  const plan = job.plans.at(-1);
  if (!plan) {
    return element("div", { class: "blank" }, element("h2", {}, "План ещё не составлен"),
      element("p", { class: "body-copy" }, "Опишите ход работы, ресурсы и критерии, по которым будет принят результат."),
      button("Составить план", () => proposePlan(job), { symbol: "plus" }));
  }
  const decision = job.planDecisions.find((item) => item.hash === plan.hash);
  const approved = decision?.decision === "approve";
  const controls = [];
  if (job.stage === "planning") controls.push(button("Новая версия плана", () => proposePlan(job)));
  if (job.stage === "awaiting_plan") {
    controls.push(
      button("Одобрить план", () => decidePlan(job, plan, "approve"), { symbol: "check" }),
      button("На доработку", () => decidePlan(job, plan, "revise"), { variant: "secondary" }),
      button("Новая версия", () => proposePlan(job), { variant: "ghost" }),
    );
  }
  return element("div", {},
    element("header", { class: "panel-header" },
      element("h2", {}, approved ? "Согласованный план" : "План работы"),
      currentVersion(plan.hash, plan.version)),
    element("p", { class: "body-copy multiline" }, plan.summary),
    section("Ресурсы", element("div", { class: "chips" }, plan.resources.map((resource) =>
      element("span", { class: "chip" }, icon("folder"), resource)))),
    section("Критерии приёмки", list(plan.criteria)),
    decision?.note ? section("Комментарий к плану", element("p", { class: "note multiline" }, decision.note)) : null,
    controls.length ? element("div", { class: "button-row" }, controls) : null,
    job.plans.length > 1 ? element("details", { class: "history" },
      element("summary", {}, "Предыдущие версии плана"),
      element("div", { class: "stack" }, job.plans.slice(0, -1).reverse().map((item) =>
        element("article", { class: "history-item" }, currentVersion(item.hash, item.version),
          element("p", { class: "body-copy multiline" }, item.summary),
          section("Ресурсы", list(item.resources)), section("Критерии", list(item.criteria)))))) : null);
}

function commentsPanel(job) {
  const messages = [...job.comments].reverse();
  return element("div", {},
    element("header", { class: "panel-header" }, element("h2", {}, "Обсуждение"),
      button("Добавить", () => addComment(job), { variant: "secondary", symbol: "plus" })),
    messages.length ? element("div", { class: "stack" }, messages.map((message) =>
      element("article", { class: "message" }, person(message.actor, message.role, when(message.at)),
        element("p", { class: "body-copy multiline" }, message.body)))) :
      element("p", { class: "body-copy" }, "Здесь можно оставить вопрос, уточнение или решение по задаче."));
}

function reference(value) {
  try {
    const url = new URL(value);
    if (["http:", "https:"].includes(url.protocol)) {
      return element("a", { class: "evidence-link", href: url.href, target: "_blank", rel: "noopener noreferrer" }, value);
    }
  } catch {
    // A reference can also be a filename or another plain-text identifier.
  }
  return value;
}

function resultsPanel(job) {
  const result = job.submissions.at(-1);
  const review = result && job.reviews.find((item) => item.hash === result.hash);
  const resultBlock = result ? element("div", {},
    element("header", { class: "panel-header" }, element("h2", {}, "Результат работы"), currentVersion(result.hash, result.version)),
    element("p", { class: "body-copy multiline" }, result.summary),
    section("Материалы для проверки", list(result.evidence, reference)),
    review ? section(review.decision === "accept" ? "Результат принят" : "Замечания ревьюера",
      element("p", { class: "note multiline" }, review.note || "Ревьюер принял эту версию.")) : null,
    job.stage === "review" ? element("div", { class: "button-row" },
      button("Принять результат", () => reviewResult(job, result, "accept"), { symbol: "check" }),
      button("На доработку", () => reviewResult(job, result, "revise"), { variant: "secondary" })) : null) :
    element("div", { class: "blank" }, element("h2", {}, "Материалов пока нет"),
      element("p", { class: "body-copy" }, "Итоги и ссылки появятся здесь после передачи на ревью."));
  const history = job.effects.length ? element("details", { class: "history" },
    element("summary", {}, "Запросы на одобрение (" + job.effects.length + ")"),
    element("div", { class: "stack" }, [...job.effects].reverse().map((item) =>
      element("article", { class: "history-item" },
        element("h3", {}, effects[item.kind] + " · " + item.target),
        element("p", { class: "body-copy multiline" }, item.reason),
        element("p", { class: "quiet" },
          item.decision ? (item.decision.value === "approve" ? "Одобрено" : "Отклонено") : "Ожидает решения"),
        item.decision?.note ? element("p", { class: "body-copy multiline" }, item.decision.note) : null)))) : null;
  const previous = job.submissions.length > 1 ? element("details", { class: "history" },
    element("summary", {}, "Предыдущие результаты"),
    element("div", { class: "stack" }, job.submissions.slice(0, -1).reverse().map((item) =>
      element("article", { class: "history-item" }, currentVersion(item.hash, item.version),
        element("p", { class: "body-copy multiline" }, item.summary), section("Материалы", list(item.evidence, reference)))))) : null;
  return element("div", {}, resultBlock, previous, history);
}

function overviewPage() {
  const board = element("div", { class: "board" });
  const filters = { all: "Все", planning: "Планирование", awaiting_plan: "Согласование", implementation: "В работе", paused: "На паузе", review: "На ревью", done: "Завершённые" };
  function renderBoard() {
    const query = state.query.trim().toLocaleLowerCase("ru");
    const jobs = state.jobs.filter((job) =>
      (state.filter === "all" || state.filter === job.stage) &&
      (job.code + " " + job.title + " " + job.brief).toLocaleLowerCase("ru").includes(query));
    board.replaceChildren(...jobs.map((job) =>
      element("a", { class: "job-card", href: "#job/" + job.id },
        element("div", { class: "job-meta" }, element("span", { class: "job-code" }, job.code), status(job.stage)),
        element("h2", {}, job.title), element("p", {}, job.brief), when(job.updatedAt))));
    if (!jobs.length) {
      const title = state.jobs.length ? "Задачи не найдены" : "Первая задача";
      board.append(element("section", { class: "panel padded blank board-empty" },
        element("h2", {}, title), state.jobs.length ? null : button("Создать задачу", createJob, { symbol: "plus" })));
    }
  }
  const controls = element("div", { class: "filters", role: "group", "aria-label": "Этап задачи" });
  for (const [id, label] of Object.entries(filters)) {
    const item = element("button", {
      type: "button", class: "filter", "aria-pressed": String(id === state.filter),
      onclick: () => {
        state.filter = id;
        for (const sibling of controls.children) sibling.setAttribute("aria-pressed", String(sibling === item));
        renderBoard();
      },
    }, label);
    controls.append(item);
  }
  const search = element("input", {
    type: "search", placeholder: "Поиск задач", "aria-label": "Поиск задач", value: state.query,
    oninput: (event) => { state.query = event.currentTarget.value; renderBoard(); },
  });
  renderBoard();
  return element("main", { class: "page" },
    element("header", { class: "page-heading" }, element("h1", {}, "Рабочие задачи")),
    element("div", { class: "board-tools" }, controls, search), board);
}

function activityPage() {
  const job = state.jobs.find((entry) => entry.id === state.route.id);
  const events = job ? state.events.filter((entry) => entry.job_id === job.id) : state.events;
  const chooser = element("select", {
    "aria-label": "Задача", onchange: (event) => { location.hash = "#activity" + (event.target.value ? "/" + event.target.value : ""); },
  }, element("option", { value: "" }, "Все задачи"), state.jobs.map((entry) =>
    element("option", { value: entry.id, selected: entry.id === job?.id }, entry.title)));
  return element("main", { class: "page" },
    element("header", { class: "page-heading" }, element("h1", {}, "Журнал"),
      job ? element("a", { class: "text-link", href: "#job/" + job.id }, job.title) : null),
    element("div", { class: "board-tools" }, element("label", { class: "field" }, "Задача", chooser)),
    element("section", { class: "panel padded", "aria-label": "События" },
      events.length ? events.map((entry) => element("article", { class: "event-row" },
        element("div", { class: "small-gap" }, element("h2", {}, entry.title),
          element("p", { class: "muted" }, entry.actor, " · ",
            element("a", { class: "text-link", href: "#job/" + entry.job_id }, entry.job_title)),
          entry.detail ? element("p", { class: "body-copy multiline" }, entry.detail) : null),
        when(entry.at))) : element("p", { class: "body-copy" }, "Событий пока нет.")));
}

function openDialog(title, ...content) {
  dialog.replaceChildren(element("div", { class: "dialog-content" },
    element("header", { class: "panel-header" }, element("h2", { id: "dialog-title" }, title),
      button("Закрыть", () => dialog.close(), { variant: "ghost", symbol: "x", iconOnly: true })),
    ...content));
  dialog.showModal();
}

function showHelp() {
  openDialog("Как это работает",
    element("ol", { class: "line-list body-copy" },
      element("li", {}, "Планировщик задаёт ход работы, ресурсы и критерии приёмки."),
      element("li", {}, "Владелец одобряет конкретную версию плана."),
      element("li", {}, "Исполнитель работает по плану и запрашивает одобрение внешних действий. Продолжение становится доступно после решения."),
      element("li", {}, "Ревьюер проверяет результат по материалам и принимает его или возвращает с замечаниями.")));
}

function textField(name, label, { value = "", limit = 1600, required = true, multiline = false, hint } = {}) {
  const attrs = { name, required, maxlength: limit, autocomplete: "off" };
  const control = multiline ? element("textarea", attrs, value) : element("input", { ...attrs, value });
  return element("label", { class: "field" }, label, control, hint ? element("span", { class: "quiet" }, hint) : null);
}

function selectField(name, label, choices) {
  return element("label", { class: "field" }, label, element("select", { name, required: true },
    element("option", { value: "", disabled: true, selected: true }, "Выберите вариант"),
    choices.map(([value, title]) => element("option", { value }, title))));
}

function showForm({ title, description, fields, submit, variant, save, onSaved, collect = (values) => values }) {
  const error = element("p", { class: "form-error", role: "alert", hidden: true });
  const cancel = button("Отмена", () => dialog.close(), { variant: "secondary" });
  const submitButton = button(submit, null, { type: "submit", variant });
  let operation;
  let submitting = false;
  const form = element("form", { class: "form", onsubmit: async (event) => {
    event.preventDefault();
    if (submitting) return;
    error.hidden = true;
    submitting = submitButton.disabled = true;
    try {
      const data = collect(Object.fromEntries(new FormData(form)));
      const fingerprint = JSON.stringify(data);
      if (operation?.fingerprint !== fingerprint) operation = { fingerprint, id: crypto.randomUUID() };
      const result = await save(data, operation.id);
      if (dialog.contains(form)) dialog.close();
      await onSaved(result);
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
      if (problem.code === "stale_revision") await refresh();
    } finally {
      submitting = submitButton.disabled = false;
    }
  } }, fields, error, element("div", { class: "form-actions" }, cancel, submitButton));
  openDialog(title, description && element("p", { class: "body-copy multiline" }, description), form);
  form.querySelector("input, textarea, select, button[type=submit]").focus();
}

const splitLines = (value) => value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);

function command(job, kind, options, tab = state.tab) {
  showForm({
    ...options,
    save: (data, operationId) => api("/api/jobs/" + job.id + "/commands",
      { operationId, type: kind, revision: job.revision, data }),
    onSaved: async ({ events }) => {
      state.tab = tab;
      await refresh();
      showNotice(events[0].title);
    },
  });
}

function createJob() {
  showForm({
    title: "Новая задача", submit: "Создать задачу",
    fields: [textField("title", "Название", { limit: 96 }), textField("brief", "Описание задачи", { multiline: true })],
    save: (data, operationId) => api("/api/jobs", { data, operationId }),
    onSaved: async ({ job }) => {
      location.hash = "#job/" + job.id;
      showNotice("Задача создана");
    },
  });
}

function editTeam(job) {
  command(job, "update_team", {
    title: "Изменить роли", submit: "Сохранить",
    fields: Object.entries(job.team).map(([role, name]) => textField(role, roles[role], { value: name, limit: 72 })),
  });
}

function proposePlan(job) {
  const previous = job.plans.at(-1);
  command(job, "propose_plan", {
    title: previous ? "Новая версия плана" : "Составить план", submit: "На согласование",
    fields: [
      textField("summary", "План работы", { multiline: true, limit: 2400, value: previous?.summary }),
      textField("resources", "Ресурсы", { multiline: true, limit: 3000, value: previous?.resources.join("\n"), hint: "По одному ресурсу на строку" }),
      textField("criteria", "Критерии приёмки", { multiline: true, limit: 3000, value: previous?.criteria.join("\n"), hint: "По одному критерию на строку" }),
    ],
    collect: (data) => ({ ...data, resources: splitLines(data.resources), criteria: splitLines(data.criteria) }),
  });
}

function decidePlan(job, plan, decision) {
  const approve = decision === "approve";
  command(job, "decide_plan", {
    title: approve ? "Одобрить план" : "Вернуть план на доработку",
    description: "Версия " + plan.version + " · " + plan.hash.slice(0, 12) + "\n" + plan.summary,
    submit: approve ? "Одобрить версию" : "Вернуть на доработку",
    fields: [textField("note", "Комментарий", { multiline: true, required: !approve })],
    collect: (data) => ({ ...data, hash: plan.hash, decision }),
  });
}

function requestEffect(job) {
  command(job, "request_effect", {
    title: "Запросить одобрение", description: "Задача останется на паузе до решения владельца.",
    submit: "Запросить одобрение",
    fields: [
      selectField("kind", "Тип действия", Object.entries(effects)),
      selectField("target", "Ресурс", job.plans.at(-1).resources.map((name) => [name, name])),
      textField("reason", "Описание действия", { multiline: true }),
    ],
  });
}

function decideEffect(job, request) {
  const type = effects[request.kind];
  command(job, "decide_effect", {
    title: "Решение по действию", description: type + " · " + request.target + "\n" + request.reason,
    submit: "Записать решение",
    fields: [
      selectField("decision", "Решение", [["approve", "Одобрить"], ["deny", "Отклонить"]]),
      textField("note", "Комментарий", { multiline: true, required: false, hint: "При отклонении укажите причину" }),
    ],
    collect: (data) => ({ ...data, hash: request.hash }),
  });
}

function resumeJob(job, request) {
  command(job, "resume_work", {
    title: "Продолжить работу", description: "Решение записано в журнале. Работа продолжится в этой же задаче.",
    submit: "Продолжить", fields: [],
    collect: () => ({ hash: request.hash }),
  });
}

function submitReview(job) {
  const previous = job.submissions.at(-1);
  command(job, "submit_review", {
    title: "Передать на ревью", submit: "Отправить результат",
    fields: [
      textField("summary", "Результат", { multiline: true, limit: 2400, value: previous?.summary }),
      textField("evidence", "Материалы для проверки", {
        multiline: true, limit: 3000, value: previous?.evidence.join("\n"), hint: "Ссылка, путь или название. По одному материалу на строку.",
      }),
    ],
    collect: (data) => ({ ...data, evidence: splitLines(data.evidence) }),
  }, "results");
}

function reviewResult(job, result, decision) {
  const accept = decision === "accept";
  command(job, "decide_review", {
    title: accept ? "Принять результат" : "Вернуть результат на доработку",
    description: "Версия " + result.version + " · " + result.hash.slice(0, 12),
    submit: accept ? "Принять и завершить" : "Вернуть на доработку",
    fields: [textField("note", "Комментарий ревью", { multiline: true, required: !accept })],
    collect: (data) => ({ ...data, hash: result.hash, decision }),
  }, "results");
}

function addComment(job) {
  command(job, "comment", {
    title: "Добавить сообщение", submit: "Отправить",
    fields: [selectField("role", "Роль автора", Object.entries(roles)), textField("body", "Сообщение", { multiline: true })],
  }, "comments");
}

window.addEventListener("hashchange", refresh);
refresh();
