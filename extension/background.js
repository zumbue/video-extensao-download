const MENUS = [
  { id: "mde-page", title: "Baixar mídia desta página", contexts: ["page"] },
  { id: "mde-link", title: "Baixar mídia deste link", contexts: ["link"] },
];

function createMenus() {
  for (const menu of MENUS) {
    chrome.contextMenus.create({
      id: menu.id,
      title: menu.title,
      contexts: menu.contexts,
    });
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => createMenus());
});

chrome.contextMenus.onClicked.addListener(async (info) => {
  const url = info.linkUrl || info.pageUrl;
  if (!url || !/^https?:/i.test(url)) {
    return;
  }
  await chrome.storage.session.set({ pendingUrl: url });
  try {
    await chrome.action.openPopup();
  } catch {
    // O popup abre no próximo clique no ícone e usa o link guardado.
  }
});
