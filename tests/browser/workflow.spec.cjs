const { expect, test } = require("@playwright/test");

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
