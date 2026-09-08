export const OPERATION_TOKEN = "browser-operation-token";
export const SESSION_ID = "browser-session";

export async function installOpsAuthMocks(context, page) {
  await context.addCookies([{
    name: "polarisUserToken",
    value: "browser-session",
    url: "http://127.0.0.1:4173",
  }]);
  await page.addInitScript(({ token, sessionId }) => {
    localStorage.setItem("OPERATION_TOKEN", token);
    localStorage.setItem("OPERATION_USER_TOKEN", sessionId);
    localStorage.setItem("OPERATION_USER_INFO", JSON.stringify({ email: "user@example.com" }));
  }, { token: OPERATION_TOKEN, sessionId: SESSION_ID });
}
