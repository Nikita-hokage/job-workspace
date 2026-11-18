const { expect, test } = require("@playwright/test");
const { readFile } = require("node:fs/promises");
const { randomUUID } = require("node:crypto");

function button(scope, name) {
  return scope.getByRole("button", { name, exact: true });
}

test("задача проходит от плана до приёмки после доработки", async ({ page }) => {
  const dialog = page.getByRole("dialog");
  const name = "Обновить руководство по установке";
  const resource = "docs/install.md";
  const feedback = "Добавьте пример запуска в Windows.";
  const revised = "Добавлен пример запуска в Windows.";

  await test.step("Создать задачу в чистой базе", async () => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Первая задача" })).toBeVisible();

    await button(page, "Новая задача").click();
    await dialog.getByLabel("Название").fill(name);
    await dialog.getByLabel("Описание задачи").fill("Проверить команды установки на чистом окружении.");
    await button(dialog, "Создать задачу").click();

    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
    await expect(page).toHaveURL(/#job\/[1-9]\d*$/);
  });

  const jobUrl = page.url();

  await test.step("Согласовать план", async () => {
    await button(page, "Составить план").click();
    await dialog.getByLabel("План работы").fill("Сверить команды и обновить руководство.");
    await dialog.getByLabel("Ресурсы").fill(resource);
    await dialog.getByLabel("Критерии приёмки").fill("По инструкции можно запустить приложение.");
    await button(dialog, "На согласование").click();

    await button(page, "Одобрить план").click();
    await button(dialog, "Одобрить версию").click();
    await expect(page.getByRole("heading", { name: "Согласованный план" })).toBeVisible();
  });

  await test.step("Сохранить паузу и продолжить после одобрения", async () => {
    await button(page, "Запросить одобрение").click();
    await dialog.getByLabel("Тип действия").selectOption("publish");
    await dialog.getByLabel("Ресурс").selectOption(resource);
    await dialog.getByLabel("Описание действия").fill("Заменить текущий раздел установки.");
    await button(dialog, "Запросить одобрение").click();

    const pending = page.getByRole("heading", { name: "Ожидается одобрение действия" });
    await expect(pending).toBeVisible();
    await page.reload();
    await expect(pending).toBeVisible();
    await expect(page).toHaveURL(jobUrl);
    await expect(button(page, "Продолжить работу")).toHaveCount(0);
    await expect(button(page, "Передать на ревью")).toHaveCount(0);

    await button(page, "Рассмотреть запрос").click();
    await expect(dialog.getByText("Заменить текущий раздел установки.")).toBeVisible();
    await dialog.getByLabel("Решение").selectOption("approve");
    await button(dialog, "Записать решение").click();

    await expect(page.getByRole("heading", { name: "Действие одобрено", exact: true })).toBeVisible();
    await expect(button(page, "Передать на ревью")).toHaveCount(0);
    await button(page, "Продолжить работу").click();
    await button(dialog, "Продолжить").click();
    await expect(page.getByRole("heading", { name: "Работа по согласованному плану" })).toBeVisible();
    await expect(page).toHaveURL(jobUrl);
  });

  async function sendToReview(summary) {
    await button(page, "Передать на ревью").click();
    await dialog.getByLabel("Результат").fill(summary);
    await dialog.getByLabel("Материалы для проверки").fill(resource);
    await button(dialog, "Отправить результат").click();
    await expect(page.getByRole("heading", { name: "Результат на ревью" })).toBeVisible();
    await expect(page.getByText(summary, { exact: true })).toBeVisible();
  }

  await test.step("Вернуть первую версию с ревью", async () => {
    await sendToReview("Команды проверены, руководство обновлено.");
    await button(page, "На доработку").click();
    await dialog.getByLabel("Комментарий ревью").fill(feedback);
    await button(dialog, "Вернуть на доработку").click();
    await expect(page.getByRole("heading", { name: "Замечания ревьюера" })).toBeVisible();
    await expect(page.getByText(feedback, { exact: true })).toBeVisible();
  });

  await test.step("Принять вторую версию и сверить журнал", async () => {
    await sendToReview(revised);
    await button(page, "Принять результат").click();
    await expect(dialog.getByText(/Версия 2/)).toBeVisible();
    await button(dialog, "Принять и завершить").click();
    await expect(page.getByRole("main").getByText("Завершена", { exact: true })).toBeVisible();
    await expect(page).toHaveURL(jobUrl);

    await page.getByRole("link", { name: "Весь журнал", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Журнал", exact: true })).toBeVisible();
    for (const event of ["План одобрен", "Работа продолжена", "Результат возвращён на доработку", "Результат принят"]) {
      await expect(page.getByRole("heading", { name: event, exact: true })).toBeVisible();
    }
  });
});

for (const template of [
  { id: "documentation", name: "Обновление документации", title: "Обновить руководство по установке", resource: "docs/install.md" },
  { id: "onboarding", name: "Онбординг команды", title: "Обновить онбординг команды", resource: "Чек-лист первого дня" },
  { id: "release", name: "Подготовка релиза", title: "Подготовить выпуск новой версии", resource: "CHANGELOG.md" },
]) {
  test("шаблон «" + template.name + "» сохраняет черновик и позволяет скачать журнал", async ({ page }) => {
    const dialog = page.getByRole("dialog");
    if (template.id === "onboarding") await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await button(page, "Новая задача").click();
    await dialog.getByLabel("Шаблон").selectOption(template.id);
    await expect(dialog.getByLabel("Название", { exact: true })).toHaveValue(template.title);

    const title = "Мой проект — " + template.name;
    await dialog.getByLabel("Название", { exact: true }).fill(title);
    await dialog.getByLabel("Шаблон").selectOption("");
    await expect(dialog.getByLabel("Название", { exact: true })).toHaveValue(title);
    await dialog.getByLabel("Шаблон").selectOption(template.id);
    await expect(dialog.getByLabel("Название", { exact: true })).toHaveValue(title);
    await button(dialog, "Создать задачу").click();
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
    const jobUrl = page.url();
    await page.reload();
    await button(page, "Составить план").click();
    await expect(dialog.getByLabel("План работы")).not.toHaveValue("");
    await expect(dialog.getByLabel("Ресурсы")).toHaveValue(new RegExp(template.resource.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    await expect(dialog.getByLabel("Критерии приёмки")).not.toHaveValue("");
    await button(dialog, "На согласование").click();
    await button(page, "Одобрить план").click();
    await button(dialog, "Одобрить версию").click();
    await expect(page.getByRole("heading", { name: "Согласованный план" })).toBeVisible();

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("link", { name: "Скачать журнал", exact: true }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/^JW-\d+\.md$/);
    expect(await download.failure()).toBeNull();
    const text = await readFile(await download.path(), "utf8");
    expect(text).toContain(title);
    expect(text).toContain("**Решение** Одобрен");
    expect(text).toContain("## Журнал событий");
    await expect(page).toHaveURL(jobUrl);
    await expect(page.getByRole("heading", { name: "Согласованный план" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test("очередь направляет задачи владельцу, исполнителю и ревьюеру", async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const dialog = page.getByRole("dialog");
  const main = page.getByRole("main");
  const plan = { summary: "Сверить инструкцию", resources: ["docs/start.md"], criteria: ["Команды проверены"] };
  async function post(path, payload) {
    const response = await request.post(path, { data: { ...payload, operationId: randomUUID() } });
    expect(response.ok()).toBeTruthy();
    return (await response.json()).job;
  }
  function command(job, type, data) {
    return post("/api/jobs/" + job.id + "/commands", { revision: job.revision, type, data });
  }
  async function planned(title) {
    const job = await post("/api/jobs", { data: { title, brief: "Проверить документацию" } });
    return command(job, "propose_plan", plan);
  }
  const first = await planned("Согласовать выпуск памятки");
  let second = await planned("Проверить новый раздел");
  second = await command(second, "decide_plan", { hash: second.plans[0].hash, decision: "approve" });
  await command(second, "submit_review", { summary: "Готов новый раздел", evidence: ["docs/start.md"] });

  await page.goto("/#job/" + first.id);
  await button(page, "Изменить роли").click();
  await dialog.getByLabel("Владелец задачи").fill("Мария");
  await dialog.getByLabel("Исполнитель").fill("Олег");
  await button(dialog, "Сохранить").click();
  await expect(page.getByText("Мария", { exact: true })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Рабочее пространство" });
  await nav.getByRole("link", { name: /^Очередь/ }).click();
  const row = (job) => main.getByRole("link", { name: new RegExp(job.title) });
  await expect(main.getByRole("listitem").first()).toContainText(first.title);
  await expect(row(first)).toContainText("Владелец задачи · Мария");
  await expect(row(second)).toContainText("Проверить результат");
  await main.getByRole("link", { name: "Ревьюер", exact: true }).click();
  await expect(row(first)).toHaveCount(0);
  await page.reload();
  await row(second).click();
  await expect(main.getByRole("heading", { name: "Результат работы" })).toBeVisible();
  await button(main, "Принять результат").click();
  await button(dialog, "Принять и завершить").click();
  await expect(main.getByText("Завершена", { exact: true })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/#inbox\/reviewer$/);
  await expect(main.getByRole("heading", { name: "Для этой роли действий нет" })).toBeVisible();
  await main.getByRole("link", { name: "Показать все роли" }).click();

  await row(first).click();
  await button(main, "Одобрить план").click();
  await button(dialog, "Одобрить версию").click();
  await button(main, "Запросить одобрение").click();
  await dialog.getByLabel("Тип действия").selectOption("publish");
  await dialog.getByLabel("Ресурс").selectOption("docs/start.md");
  await dialog.getByLabel("Описание действия").fill("Опубликовать памятку");
  await button(dialog, "Запросить одобрение").click();
  await expect(main.getByRole("heading", { name: "Ожидается одобрение действия" })).toBeVisible();
  await nav.getByRole("link", { name: /^Очередь/ }).click();
  await expect(row(first)).toContainText("Рассмотреть запрос");
  await row(first).click();
  await button(main, "Рассмотреть запрос").click();
  await dialog.getByLabel("Решение").selectOption("approve");
  await button(dialog, "Записать решение").click();
  await expect(main.getByRole("heading", { name: "Действие одобрено", exact: true })).toBeVisible();
  await page.goBack();
  await main.getByRole("link", { name: "Исполнитель", exact: true }).click();
  await expect(row(first)).toContainText("Исполнитель · Олег");
  await expect(row(first)).toContainText("Продолжить работу");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await row(first).click();
  await button(main, "Продолжить работу").click();
  await button(dialog, "Продолжить").click();
  await expect(main.getByRole("heading", { name: "Работа по согласованному плану" })).toBeVisible();
  await page.goBack();
  await expect(main.getByRole("heading", { name: "Очередь пуста" })).toBeVisible();
});
