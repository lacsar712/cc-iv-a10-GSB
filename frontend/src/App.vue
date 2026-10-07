<template>
  <main>
    <template v-if="!session">
      <h1>光伏组串IV扫描台</h1>
      <p class="sub">扫描员提交开路电压、短路电流与填充因子；通知通道叫醒工人出结论。登录框已预填可写账号 scanner / scan123456。</p>
      <section>
        <label>用户名</label><input v-model="loginUser" autocomplete="off" />
        <label>密码</label><input type="password" v-model="loginPass" autocomplete="off" />
        <button :disabled="loading" @click="login">登录</button>
        <p v-if="error" class="err">{{ error }}</p>
      </section>
    </template>
    <template v-else>
      <header class="topbar">
        <h1>光伏组串IV扫描台</h1>
        <nav>
          <button class="secondary" :class="{ active: view === 'scan' }" @click="view = 'scan'">扫描台</button>
          <button class="secondary" :class="{ active: view === 'hot' }" @click="goHot">
            红外超温名单<span v-if="activeCount" class="badge">{{ activeCount }}</span>
          </button>
          <button class="secondary" @click="refreshAll">刷新</button>
          <button class="secondary" @click="logout">退出</button>
        </nav>
      </header>
      <p class="sub">已登录：{{ session.username }}（{{ isWriter ? "可提交" : "观察员只读" }}）</p>

      <!-- 扫描台主页 -->
      <div v-if="view === 'scan'">
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

      <!-- 红外超温名单专页：左列开关 / 中列超温组串 / 右列挡回痕迹 -->
      <div v-if="view === 'hot'">
        <p class="sub">
          红外热像点名的组串，名单开启期间其新扫描整份挡回；挡回痕迹与真实拒收同批记录。
          <template v-if="!isWriter">观察员只能查看，不能扳动开关或点名。</template>
        </p>
        <p v-if="hotError" class="err">{{ hotError }}</p>
        <div class="cols">
          <!-- 左列：开关 -->
          <section>
            <h2>开关</h2>
            <p v-if="!hotEntries.length" class="muted">名单为空</p>
            <div v-for="entry in hotEntries" :key="entry.id" class="switch-row">
              <div class="switch-code">{{ entry.string_code }}</div>
              <button
                class="switch"
                :class="entry.active ? 'on' : 'off'"
                :disabled="!isWriter || hotBusy"
                @click="toggleHot(entry)"
              >
                <span class="knob"></span>{{ entry.active ? "名单开·拦截中" : "名单关" }}
              </button>
            </div>
            <p v-if="!isWriter && hotEntries.length" class="muted small">观察员可看不能扳开关</p>
          </section>

          <!-- 中列：超温组串 -->
          <section>
            <h2>超温组串</h2>
            <div v-if="isWriter" class="addline">
              <input v-model="hotCode" placeholder="点名组串，例如 阵列D-串07" autocomplete="off" @keyup.enter="addHot" />
              <button :disabled="hotBusy" @click="addHot">点名入队</button>
            </div>
            <p v-if="!hotEntries.length" class="muted">还没有组串被点名为超温</p>
            <div v-for="entry in hotEntries" :key="'m' + entry.id" class="entry">
              <div class="entry-head">
                <strong>{{ entry.string_code }}</strong>
                <span class="tag" :class="entry.active ? 'bad' : 'ok'">{{ entry.active ? "超温拦截中" : "已放行" }}</span>
              </div>
              <div class="muted small">点名：{{ entry.created_by }} · {{ fmt(entry.created_at) }}</div>
              <div class="muted small">最近操作：{{ entry.updated_by || entry.created_by }} · {{ fmt(entry.updated_at) }}</div>
            </div>
          </section>

          <!-- 右列：挡回痕迹 -->
          <section>
            <h2>挡回痕迹</h2>
            <p v-if="!hotTraces.length" class="muted">暂无挡回记录</p>
            <div v-for="trace in hotTraces" :key="trace.id" class="trace">
              <div class="entry-head">
                <strong>#{{ trace.id }} {{ trace.string_code }}</strong>
                <span class="tag bad">已挡回</span>
              </div>
              <div class="small">Voc {{ trace.voc_v }} / Isc {{ trace.isc_a }} / FF {{ trace.fill_factor }}</div>
              <div class="muted small">提交人 {{ trace.submitted_by }} · {{ fmt(trace.blocked_at) }}</div>
              <div class="small reason">{{ trace.reason }}</div>
            </div>
          </section>
        </div>
      </div>
    </template>
  </main>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
const session = ref(null);
const logs = ref([]);
const loginUser = ref("scanner");
const loginPass = ref("scan123456");
const stringCode = ref("");
const voc = ref("");
const isc = ref("");
const ff = ref("");
const error = ref("");
const loading = ref(false);
const view = ref("scan");
const hotEntries = ref([]);
const hotTraces = ref([]);
const hotCode = ref("");
const hotError = ref("");
const hotBusy = ref(false);
let timer;
const isWriter = computed(() => session.value?.role === "writer");
const activeCount = computed(() => hotEntries.value.filter((e) => e.active).length);
function headers() {
  return session.value ? { Authorization: "Bearer " + session.value.token } : {};
}
function fmt(ts) {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("zh-CN", { hour12: false });
}
async function refreshLogs() {
  const res = await fetch("/api/logs", { headers: headers() });
  if (res.status === 401) { logout(); return; }
  if (res.ok) logs.value = await res.json();
}
async function refreshHot() {
  const res = await fetch("/api/hot-list", { headers: headers() });
  if (res.status === 401) { logout(); return; }
  if (res.ok) {
    const data = await res.json();
    hotEntries.value = data.entries || [];
    hotTraces.value = data.traces || [];
  }
}
function tick() {
  if (!session.value) return;
  // 名单始终刷新，顶栏角标与当前页数据都保持实时
  refreshHot();
  if (view.value !== "hot") refreshLogs();
}
function refreshAll() {
  if (!session.value) return;
  if (view.value === "hot") return refreshHot();
  return refreshLogs();
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
    await refreshLogs();
    await refreshHot();
    timer = setInterval(tick, 2000);
  } catch { error.value = "无法连接接口"; }
  finally { loading.value = false; }
}
function logout() {
  if (timer) clearInterval(timer);
  session.value = null;
  logs.value = [];
  hotEntries.value = [];
  hotTraces.value = [];
  view.value = "scan";
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
    if (!res.ok) {
      // 名单开启时后端 409 整份挡回，原因与挡回痕迹同批落库
      error.value = data.detail || "提交失败";
      return;
    }
    stringCode.value = voc.value = isc.value = ff.value = "";
    await refreshLogs();
  } catch { error.value = "提交时网络异常"; }
  finally { loading.value = false; }
}
function goHot() {
  view.value = "hot";
  hotError.value = "";
  refreshHot();
}
async function addHot() {
  const code = hotCode.value.trim();
  if (!code) { hotError.value = "组串编号不能为空"; return; }
  hotError.value = "";
  hotBusy.value = true;
  try {
    const res = await fetch("/api/hot-list", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({ string_code: code }),
    });
    const data = await res.json();
    if (!res.ok) { hotError.value = data.detail || "点名失败"; return; }
    hotCode.value = "";
    await refreshHot();
  } catch { hotError.value = "点名时网络异常"; }
  finally { hotBusy.value = false; }
}
async function toggleHot(entry) {
  hotError.value = "";
  hotBusy.value = true;
  try {
    const res = await fetch("/api/hot-list/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({ string_code: entry.string_code, active: !entry.active }),
    });
    const data = await res.json();
    if (!res.ok) { hotError.value = data.detail || "开关操作失败"; return; }
    await refreshHot();
  } catch { hotError.value = "扳开关时网络异常"; }
  finally { hotBusy.value = false; }
}
onMounted(() => {
  const raw = localStorage.getItem("pv_session");
  if (raw) {
    try {
      session.value = JSON.parse(raw);
      refreshLogs();
      refreshHot();
      timer = setInterval(tick, 2000);
    } catch { localStorage.removeItem("pv_session"); }
  }
});
onUnmounted(() => { if (timer) clearInterval(timer); });
</script>
<style>
body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #052e16; color: #ecfdf5; }
main { max-width: 1180px; margin: 0 auto; padding: 1.5rem; }
h1 { color: #86efac; margin: 0; font-size: 1.4rem; }
h2 { color: #86efac; margin: 0 0 0.75rem; font-size: 1.05rem; }
.sub { color: #a7f3d0; margin-bottom: 1.25rem; }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 0.5rem; }
nav button.active { outline: 2px solid #4ade80; }
.badge { display: inline-block; min-width: 1.1rem; margin-left: 0.35rem; padding: 0 0.3rem; border-radius: 999px; background: #dc2626; color: #fff; font-size: 0.72rem; line-height: 1.15rem; text-align: center; }
section { background: #14532d; border: 1px solid #166534; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1rem; }
.cols { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; align-items: start; }
label { display: block; font-size: 0.85rem; margin-bottom: 0.25rem; }
input { width: 100%; box-sizing: border-box; padding: 0.5rem 0.65rem; border-radius: 6px; border: 1px solid #4ade80; background: #022c22; color: #ecfdf5; margin-bottom: 0.75rem; }
.addline input { margin-bottom: 0; }
.addline { display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.9rem; }
.addline button { margin-right: 0; white-space: nowrap; }
button { cursor: pointer; padding: 0.5rem 1rem; border: none; border-radius: 6px; background: #16a34a; color: #fff; font-weight: 600; margin-right: 0.4rem; }
button.secondary { background: #365314; }
button:disabled { opacity: 0.55; cursor: not-allowed; }
.err { color: #fecaca; }
.muted { color: #a7f3d0; opacity: 0.75; }
.small { font-size: 0.78rem; margin-top: 0.15rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.45rem; border-bottom: 1px solid #166534; }
.tag { padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.8rem; }
.ok { background: #14532d; color: #bbf7d0; }
.bad { background: #7f1d1d; color: #fecaca; }
.pending { background: #854d0e; color: #fde68a; }
.switch-row { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; padding: 0.55rem 0; border-bottom: 1px solid #166534; }
.switch-code { font-weight: 600; word-break: break-all; }
.switch { position: relative; padding: 0.35rem 0.6rem 0.35rem 2.1rem; border-radius: 999px; font-size: 0.78rem; margin-right: 0; min-width: 7.5rem; }
.switch .knob { position: absolute; top: 0.22rem; left: 0.25rem; width: 1.05rem; height: 1.05rem; border-radius: 50%; background: #d1fae5; transition: left 0.15s; }
.switch.off { background: #4b5563; }
.switch.off .knob { left: calc(100% - 1.3rem); }
.entry, .trace { padding: 0.6rem 0; border-bottom: 1px solid #166534; }
.entry-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.2rem; }
.trace .reason { color: #fde68a; }
</style>
