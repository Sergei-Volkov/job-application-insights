const API_BASE = "http://127.0.0.1:8000";

function renderKeyValueList(containerId, obj) {
  const el = document.getElementById(containerId);
  el.innerHTML = "";

  const entries = Object.entries(obj || {});
  if (!entries.length) {
    el.innerHTML = "<li>No data yet</li>";
    return;
  }

  entries
    .sort((a, b) => b[1] - a[1])
    .forEach(([key, value]) => {
      const li = document.createElement("li");
      li.textContent = `${key}: ${value}`;
      el.appendChild(li);
    });
}

function renderSkills(containerId, items) {
  const el = document.getElementById(containerId);
  el.innerHTML = "";

  if (!items || !items.length) {
    el.innerHTML = "<li>No skill gaps yet</li>";
    return;
  }

  items.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = `${item.skill} (${item.count})`;
    el.appendChild(li);
  });
}

async function load() {
  try {
    const statsRes = await fetch(`${API_BASE}/stats`);
    const stats = await statsRes.json();

    document.getElementById("total").textContent = stats.total_applications ?? 0;
    renderKeyValueList("status-list", stats.by_status);
    renderKeyValueList("stage-list", stats.by_stage);

    const skillsRes = await fetch(`${API_BASE}/missing-skills`);
    const skills = await skillsRes.json();
    renderSkills("skills-list", skills.items);
  } catch (err) {
    document.getElementById("total").textContent = "Error";
    renderKeyValueList("status-list", {});
    renderKeyValueList("stage-list", {});
    renderSkills("skills-list", []);
  }
}

load();
