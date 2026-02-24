      function renderFactList(facts) {
        const list = el("facts-list");
        list.innerHTML = "";
        facts.forEach((fact) => {
          const card = document.createElement("div");
          card.className = "result-card";
          const title = document.createElement("div");
          title.textContent = fact.tag_path + " = " + JSON.stringify(fact.value);
          const meta = document.createElement("div");
          meta.className = "small mono";
          meta.textContent =
            "fact_id=" +
            fact.fact_id +
            " 상태=" +
            fact.status +
            " 출처=" +
            fact.source;
          const actions = document.createElement("div");
          actions.className = "row";
          const approveBtn = document.createElement("button");
          approveBtn.textContent = "승인";
          approveBtn.className = "secondary";
          approveBtn.addEventListener("click", () => updateFactStatus(fact.fact_id, "APPROVED"));
          const rejectBtn = document.createElement("button");
          rejectBtn.textContent = "거절";
          rejectBtn.className = "ghost";
          rejectBtn.addEventListener("click", () => updateFactStatus(fact.fact_id, "REJECTED"));
          const evidenceBtn = document.createElement("button");
          evidenceBtn.textContent = "근거";
          evidenceBtn.className = "ghost";
          evidenceBtn.addEventListener("click", () => fetchEvidence(fact.evidence_eid));
          actions.appendChild(approveBtn);
          actions.appendChild(rejectBtn);
          actions.appendChild(evidenceBtn);
          card.appendChild(title);
          card.appendChild(meta);
          card.appendChild(actions);
          list.appendChild(card);
        });
      }
      function renderMentionList(items, targetId, updateFn) {
        const list = el(targetId);
        list.innerHTML = "";
        items.forEach((item) => {
          const card = document.createElement("div");
          card.className = "result-card";
          const title = document.createElement("div");
          title.textContent = item.doc_id + " " + item.span_start + "-" + item.span_end;
          const meta = document.createElement("div");
          meta.className = "small mono";
          meta.textContent =
            "id=" + (item.mention_id || item.anchor_id || item.timeline_event_id) + " 상태=" + item.status;
          const actions = document.createElement("div");
          actions.className = "row";
          const approveBtn = document.createElement("button");
          approveBtn.textContent = "승인";
          approveBtn.className = "secondary";
          approveBtn.addEventListener("click", () => updateFn(item, "APPROVED"));
          const rejectBtn = document.createElement("button");
          rejectBtn.textContent = "거절";
          rejectBtn.className = "ghost";
          rejectBtn.addEventListener("click", () => updateFn(item, "REJECTED"));
          actions.appendChild(approveBtn);
          actions.appendChild(rejectBtn);
          card.appendChild(title);
          card.appendChild(meta);
          card.appendChild(actions);
          list.appendChild(card);
        });
      }
