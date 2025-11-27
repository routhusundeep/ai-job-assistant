chrome.runtime.onInstalled.addListener(() => {
  console.log("AI Job Assistant extension installed");
});

// Inject content script on matching pages by user action (popup) or declarative in future.
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id || !tab.url) return;
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["content.js"],
  });
});
