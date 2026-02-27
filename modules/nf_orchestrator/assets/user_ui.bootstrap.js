// Init
init();

// Auto-load session
const lastPid = localStorage.getItem("last_project_id");
const lastName = localStorage.getItem("last_project_name");
if (lastPid && lastName) {
  loadProject(lastPid, lastName);
  document.getElementById("setup-modal").classList.remove("active");
}

function openGlobalSettings() {
  document.getElementById("global-api-key").value = localStorage.getItem("nf_api_key") || "";
  document.getElementById("global-local-model").value = localStorage.getItem("nf_api_model") || "";
  document.getElementById("global-settings-modal").classList.add("active");
}

function closeGlobalSettings() {
  document.getElementById("global-settings-modal").classList.remove("active");
}

function saveGlobalSettings() {
  const apiKey = document.getElementById("global-api-key").value.trim();
  const model = document.getElementById("global-local-model").value.trim();
  if (apiKey) localStorage.setItem("nf_api_key", apiKey);
  else localStorage.removeItem("nf_api_key");

  if (model) localStorage.setItem("nf_api_model", model);
  else localStorage.removeItem("nf_api_model");

  closeGlobalSettings();
  if (typeof showSuccess === "function") showSuccess("설정이 저장되었습니다.");
}

// Explicit inline-handler exports
window.openGlobalSettings = openGlobalSettings;
window.closeGlobalSettings = closeGlobalSettings;
window.saveGlobalSettings = saveGlobalSettings;
window.closeExportModal = closeExportModal;
window.closeSuccessPopup = closeSuccessPopup;
window.createNewChapter = createNewChapter;
window.createNewDoc = createNewDoc;
window.execCmd = execCmd;
window.exitProject = exitProject;
window.fetchRecentJobs = fetchRecentJobs;
window.handleComposition = handleComposition;
window.handleCreateProject = handleCreateProject;
window.handleDragOver = handleDragOver;
window.handleDragStart = handleDragStart;
window.handleDropOnItem = handleDropOnItem;
window.handleExport = handleJobExport;
window.handleInput = handleInput;
window.handleLoadProject = handleLoadProject;
window.loadDoc = loadDoc;
window.openDocCtxMenu = openDocCtxMenu;
window.openExportModal = openExportModal;
window.openGroupCtxMenu = openGroupCtxMenu;
window.runAssistantAction = runAssistantAction;
window.switchAssistTab = switchAssistTab;
window.switchNavTab = switchNavTab;
window.toggleConfigPanel = toggleConfigPanel;
window.toggleConsistencyPanel = toggleConsistencyPanel;
window.toggleJobsPanel = toggleJobsPanel;
window.toggleLeftSidebar = toggleLeftSidebar;
window.toggleRightSidebar = toggleRightSidebar;
window.openRightSidebar = openRightSidebar;
window.closeRightSidebar = closeRightSidebar;
window.updateEditorConfig = updateEditorConfig;
