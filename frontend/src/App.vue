<template>
  <main>
    <h1>光伏组串IV扫描台</h1>
    <div v-if="!session">
      <p class="sub">扫描员提交开路电压、短路电流与填充因子；通知通道叫醒工人出结论。登录框已预填可写账号 scanner / scan123456。</p>
      <section>
        <label>用户名</label><input v-model="loginUser" autocomplete="off" />
        <label>密码</label><input type="password" v-model="loginPass" autocomplete="off" />
        <button :disabled="loading" @click="login">登录</button>
        <p v-if="error" class="err">{{ error }}</p>
      </section>
    </div>
    <div v-else>
      <nav class="topbar">
        <button class="nav" :class="{ active: view === 'scan' }" @click="view = 'scan'">扫描台</button>
        <button class="nav hot" :class="{ active: view === 'overtemp' }" @click="goOvertemp">
          超温名单<span v-if="overtemp.enabled" class="dot">●</span>
        </button>
        <span class="spacer"></span>
        <span class="who">{{ session.username }}（{{ isWriter ? "可提交" : "只读" }}）</span>
        <button class="secondary" @click="logout">退出</button>
      </nav>

      <!-- 扫描台 -->
      <div v-show="view === 'scan'">
        <p class="sub">已登录：{{ session.username }}（{{ isWriter ? "可提交" : "只读" }}）</p>
        <section>
          <button class="secondary" @click="refresh">刷新列表</button>
        </section>
        <section v-if="isWriter">
          <label>组串编号</label><input v-model="stringCode" placeholder="例如 阵列C-串05" />
          <label>开路电压 V</label><input type="number" step="0.1" v-model="voc" />
          <label>短路电流 A</label><input type="number" step="0.1" v-model="isc" />
          <label>填充因子</label><input type="number" step="0.01" v-model="ff" />
          <button :disabled="loading" @click="submit">提交扫描</button>
          <p v-if="error" class="err">{{ error }}</p>
        </section>
        <section>
          <table>
            <thead>
              <tr><th>编号</th><th>组串</th><th>Voc</th><th>Isc</th><th>FF</th><th>状态</th><th>结论</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in logs" :key="row.id">
                <td>{{ row.id }}</td>
                <td>{{ row.string_code }}</td>
                <td>{{ row.voc_v }}</td>
                <td>{{ row.isc_a }}</td>
                <td>{{ row.fill_factor }}</td>
                <td><span class="tag" :class="row.status === 'pending' ? 'pending' : 'ok'">{{ row.status === 'pending' ? '待处理' : '已完成' }}</span></td>
                <td><span v-if="row.verdict" class="tag" :class="row.verdict === '合格' ? 'ok' : 'bad'">{{ row.verdict }}</span><span v-else>—</span></td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <!-- 超温名单专页：左开关 / 中超温组串 / 右挡回痕迹 -->
      <div v-show="view === 'overtemp'">
        <p v-if="!isWriter" class="err">只读账号：可查看名单与挡回痕迹，不能扳开关或点名组串。</p>
        <p v-if="otError" class="err">{{ otError }}</p>
        <div class="cols">
          <!-- 左列：开关 -->
          <section class="col">
            <h2>名单开关</h2>
            <p class="hint">总开关打开且组串被点名时，该串新扫描整份拒收、不进队列；关掉后新单不再拦。</p>
            <div class="switch-row">
              <span>总开关</span>
              <button class="switch" :class="overtemp.enabled ? 'on' : 'off'"
                      :disabled="!isWriter || loading"
                      @click="setSwitch(!overtemp.enabled)">
                {{ overtemp.enabled ? "已开启" : "已关闭" }}
              </button>
            </div>
            <p class="hint" v-if="overtemp.updated_by">
              最后扳动：{{ overtemp.updated_by }} · {{ fmtTime(overtemp.updated_at) }}
            </p>
            <button class="secondary" @click="loadOvertemp">刷新名单</button>
          </section>

          <!-- 中列：超温组串 -->
          <section class="col">
            <h2>超温组串（{{ activeStringCount }}/{{ overtemp.strings.length }} 生效）</h2>
            <div v-if="isWriter" class="add-row">
              <input v-model="newString" placeholder="点名入队，例如 阵列C-串05"
                     @keyup.enter="addString" />
              <button :disabled="loading || !newString.trim()" @click="addString">点名入队</button>
            </div>
            <p v-if="overtemp.strings.length === 0" class="hint">名单为空。</p>
            <ul class="string-list">
              <li v-for="s in overtemp.strings" :key="s.id" :class="{ off: !s.active }">
                <span class="code">{{ s.string_code }}</span>
                <button class="switch sm" :class="s.active ? 'on' : 'off'"
                        :disabled="!isWriter || loading"
                        @click="setStringSwitch(s, !s.active)">
                  {{ s.active ? "拦截中" : "已放行" }}
                </button>
                <span class="hint">点名：{{ s.created_by }}</span>
              </li>
            </ul>
          </section>

          <!-- 右列：挡回痕迹 -->
          <section class="col">
            <h2>挡回痕迹（{{ overtemp.rejections.length }}）</h2>
            <p class="hint">挡回与拒收同批落库，只记录真实被挡回的扫描。</p>
            <p v-if="overtemp.rejections.length === 0" class="hint">暂无挡回记录。</p>
            <table class="reject-table">
              <thead>
                <tr><th>时间</th><th>组串</th><th>提交人</th><th>FF</th><th>原因</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in overtemp.rejections" :key="r.id">
                  <td class="nowrap">{{ fmtTime(r.rejected_at) }}</td>
                  <td>{{ r.string_code }}</td>
                  <td>{{ r.created_by }}</td>
                  <td>{{ r.fill_factor }}</td>
                  <td class="reason">{{ r.reason }}</td>
                </tr>
              </tbody>
            </table>
          </section>
        </div>
      </div>
    </div>
  </main>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
const session = ref(null);
const logs = ref([]);
const view = ref("scan");
const newString = ref("");
const otError = ref("");
const overtemp = ref({ enabled: false, updated_by: null, updated_at: null, strings: [], rejections: [] });
const loginUser = ref("scanner");
const loginPass = ref("scan123456");
const stringCode = ref("");
const voc = ref("");
const isc = ref("");
const ff = ref("");
const error = ref("");
const loading = ref(false);
let timer;
const isWriter = computed(() => session.value?.role === "writer");
const activeStringCount = computed(() => overtemp.value.strings.filter(s => s.active).length);
function headers() {
  return session.value ? { Authorization: "Bearer " + session.value.token } : {};
}
function fmtTime(iso) {
  if (!iso) return "—";
  return iso.replace("T", " ").replace(/\.\d+.*$/, "").replace(/\+.*$/, "");
}
async function refresh() {
  if (!session.value) return;
  const res = await fetch("/api/logs", { headers: headers() });
  if (res.status === 401) { logout(); return; }
  if (res.ok) logs.value = await res.json();
  if (view.value === "overtemp") await loadOvertemp();
}
async function loadOvertemp() {
  if (!session.value) return;
  const res = await fetch("/api/overtemp", { headers: headers() });
  if (res.status === 401) { logout(); return; }
  if (res.ok) overtemp.value = await res.json();
}
function goOvertemp() {
  view.value = "overtemp";
  otError.value = "";
  loadOvertemp();
}
async function login() {
  error.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: loginUser.value, password: loginPass.value }),
    });
    const data = await res.json();
    if (!res.ok) { error.value = data.detail || "登录失败"; return; }
    session.value = { token: data.access_token, username: data.username, role: data.role };
    localStorage.setItem("pv_session", JSON.stringify(session.value));
    await refresh();
    timer = setInterval(refresh, 2000);
  } catch { error.value = "无法连接接口"; }
  finally { loading.value = false; }
}
function logout() {
  if (timer) clearInterval(timer);
  session.value = null;
  logs.value = [];
  localStorage.removeItem("pv_session");
}
async function submit() {
  error.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/logs", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({
        string_code: stringCode.value,
        voc_v: Number(voc.value),
        isc_a: Number(isc.value),
        fill_factor: Number(ff.value),
      }),
    });
    const data = await res.json();
    if (!res.ok) { error.value = data.detail || "提交失败"; return; }
    stringCode.value = voc.value = isc.value = ff.value = "";
    await refresh();
  } catch { error.value = "提交时网络异常"; }
  finally { loading.value = false; }
}
async function otCall(url, body) {
  otError.value = "";
  loading.value = true;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { otError.value = data.detail || "操作失败"; return; }
    await loadOvertemp();
  } catch { otError.value = "网络异常"; }
  finally { loading.value = false; }
}
function setSwitch(enabled) { return otCall("/api/overtemp/switch", { enabled }); }
function setStringSwitch(s, active) { return otCall(`/api/overtemp/strings/${s.id}/switch`, { active }); }
async function addString() {
  const code = newString.value.trim();
  if (!code) return;
  await otCall("/api/overtemp/strings", { string_code: code });
  newString.value = "";
}
onMounted(() => {
  const raw = localStorage.getItem("pv_session");
  if (raw) {
    try {
      session.value = JSON.parse(raw);
      refresh();
      timer = setInterval(refresh, 2000);
    } catch { localStorage.removeItem("pv_session"); }
  }
});
onUnmounted(() => { if (timer) clearInterval(timer); });
</script>
<style>
body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #052e16; color: #ecfdf5; }
main { max-width: 1180px; margin: 0 auto; padding: 1.5rem; }
h1 { color: #86efac; margin: 0 0 0.75rem; }
h2 { color: #86efac; margin: 0 0 0.75rem; font-size: 1.05rem; }
.sub { color: #a7f3d0; margin-bottom: 1.25rem; }
section { background: #14532d; border: 1px solid #166534; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1rem; }
label { display: block; font-size: 0.85rem; margin-bottom: 0.25rem; }
input { width: 100%; box-sizing: border-box; padding: 0.5rem 0.65rem; border-radius: 6px; border: 1px solid #4ade80; background: #022c22; color: #ecfdf5; margin-bottom: 0.75rem; }
button { cursor: pointer; padding: 0.5rem 1rem; border: none; border-radius: 6px; background: #16a34a; color: #fff; font-weight: 600; margin-right: 0.4rem; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
button.secondary { background: #365314; }
.err { color: #fecaca; }
.hint { color: #a7f3d0; font-size: 0.82rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.45rem; border-bottom: 1px solid #166534; vertical-align: top; }
.tag { padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.8rem; }
.ok { background: #14532d; color: #bbf7d0; }
.bad { background: #7f1d1d; color: #fecaca; }
.pending { background: #854d0e; color: #fde68a; }
.topbar { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem; }
.topbar .spacer { flex: 1; }
.topbar .who { color: #a7f3d0; font-size: 0.9rem; }
button.nav { background: #14532d; border: 1px solid #166534; }
button.nav.active { background: #16a34a; }
button.nav.hot { color: #fecaca; }
button.nav.hot.active { background: #b91c1c; }
.dot { color: #fca5a5; margin-left: 0.3rem; }
.cols { display: grid; grid-template-columns: 1fr 1fr 1.2fr; gap: 1rem; align-items: start; }
.col { margin-bottom: 0; }
.switch-row { display: flex; align-items: center; justify-content: space-between; margin: 0.75rem 0; }
button.switch { min-width: 92px; }
button.switch.on { background: #b91c1c; }
button.switch.off { background: #365314; }
button.switch.sm { min-width: 74px; padding: 0.3rem 0.6rem; font-size: 0.8rem; }
.add-row { display: flex; gap: 0.5rem; align-items: center; }
.add-row input { margin-bottom: 0.5rem; }
.string-list { list-style: none; padding: 0; margin: 0.5rem 0 0; }
.string-list li { display: flex; align-items: center; gap: 0.5rem; padding: 0.5rem 0; border-bottom: 1px solid #166534; }
.string-list li.off .code { text-decoration: line-through; color: #a7f3d0; }
.string-list .code { font-weight: 600; flex: 1; }
.reject-table { font-size: 0.8rem; }
.reject-table .nowrap { white-space: nowrap; }
.reject-table .reason { color: #fecaca; }
</style>
