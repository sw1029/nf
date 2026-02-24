      // Init
      init();

      // Auto-load session
      const lastPid = localStorage.getItem("last_project_id");
      const lastName = localStorage.getItem("last_project_name");
      if (lastPid && lastName) {
        loadProject(lastPid, lastName);
        document.getElementById("setup-modal").classList.remove("active");
      }

// Explicit inline-handler exports
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
window.handleExport = handleExport;
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
window.updateEditorConfig = updateEditorConfig;
