package com.airiradar.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 首页：原生日报列表（离线优先）。
 * 数据来源：打包进 APK 的 assets/index.json（永远可用）；
 * 联网时从电脑同步最新日报到内部存储，并与之合并。
 */
public class MainActivity extends Activity {

    static final String PREFS = "airiradar";
    static final String KEY_SERVER = "server_url";
    static final String KEY_READ = "read_dates";
    static final String DEFAULT_SERVER = "http://192.168.1.100:8899";

    private final Handler ui = new Handler(Looper.getMainLooper());

    private TextView statusText;
    private ListView listView;
    private ReportAdapter adapter;
    private final List<ReportItem> items = new ArrayList<>();
    private final Set<String> readDates = new HashSet<>();

    private String serverUrl = DEFAULT_SERVER;
    private boolean syncing = false;

    /** 单条日报（列表展示用）。 */
    static class ReportItem {
        String date;
        String summary;
        int events, models, chances, aLevel;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        statusText = findViewById(R.id.status_text);
        listView = findViewById(R.id.list);
        adapter = new ReportAdapter();
        listView.setAdapter(adapter);

        SharedPreferences sp = getSharedPreferences(PREFS, MODE_PRIVATE);
        serverUrl = sp.getString(KEY_SERVER, DEFAULT_SERVER);
        Set<String> read = sp.getStringSet(KEY_READ, null);
        if (read != null) readDates.addAll(read);

        findViewById(R.id.btn_sync).setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { doSync(); }
        });
        findViewById(R.id.btn_settings).setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { showSettings(); }
        });

        listView.setOnItemClickListener(new AdapterView.OnItemClickListener() {
            @Override
            public void onItemClick(AdapterView<?> parent, View v, int pos, long id) {
                ReportItem it = items.get(pos);
                if (!readDates.contains(it.date)) {          // 首次打开标记已读
                    readDates.add(it.date);
                    saveReadPrefs();
                    postReadToServer(it.date);
                    adapter.notifyDataSetChanged();
                }
                Intent i = new Intent(MainActivity.this, ReaderActivity.class);
                i.putExtra("date", it.date);
                startActivity(i);
            }
        });

        // 先显示打包在 App 里的日报（离线立即可用）
        loadIndex();
        adapter.notifyDataSetChanged();
        setStatus(getString(R.string.status_offline, items.size()));

        // 后台自动同步电脑上最新日报（失败静默，不影响使用）
        doSync();
    }

    // ------------------------------------------------------------------
    // 数据加载
    // ------------------------------------------------------------------

    /** 加载日报列表：优先内部存储（已同步），否则用打包进 App 的 assets。 */
    private boolean loadIndex() {
        String text = null;
        File synced = new File(getFilesDir(), "index.json");
        if (synced.exists()) {
            try { text = readString(synced); } catch (IOException ignored) { }
        }
        if (text == null) {
            try { text = readAssetString("index.json"); } catch (IOException ignored) { }
        }
        if (text == null) return false;
        try {
            JSONArray arr = new JSONObject(text).getJSONArray("reports");
            items.clear();
            for (int i = 0; i < arr.length(); i++) {
                items.add(fromJson(arr.getJSONObject(i)));
            }
            sortItems();
            return true;
        } catch (JSONException e) {
            return false;
        }
    }

    private ReportItem fromJson(JSONObject o) throws JSONException {
        ReportItem it = new ReportItem();
        it.date = o.getString("date");
        it.summary = o.optString("summary", "");
        JSONObject st = o.optJSONObject("stats");
        it.events = st != null ? st.optInt("events", 0) : 0;
        it.models = st != null ? st.optInt("models", 0) : 0;
        it.chances = st != null ? st.optInt("chances", 0) : 0;
        it.aLevel = st != null ? st.optInt("a_level", 0) : 0;
        return it;
    }

    private void sortItems() {
        Collections.sort(items, new Comparator<ReportItem>() {
            @Override public int compare(ReportItem a, ReportItem b) {
                return b.date.compareTo(a.date);
            }
        });
    }

    // ------------------------------------------------------------------
    // 同步
    // ------------------------------------------------------------------

    private void doSync() {
        if (syncing) return;
        syncing = true;
        setStatus(getString(R.string.status_syncing));
        new Thread(new Runnable() {
            @Override public void run() {
                final boolean ok = trySync();
                ui.post(new Runnable() {
                    @Override public void run() {
                        syncing = false;
                        if (ok) {
                            setStatus(getString(R.string.status_synced, items.size()));
                            Toast.makeText(MainActivity.this, "已同步最新日报", Toast.LENGTH_SHORT).show();
                        } else {
                            setStatus(getString(R.string.status_offline, items.size()));
                            Toast.makeText(MainActivity.this, "未连上电脑，使用本地日报", Toast.LENGTH_SHORT).show();
                        }
                        adapter.notifyDataSetChanged();
                    }
                });
            }
        }).start();
    }

    private boolean trySync() {
        try {
            URL u = new URL(serverUrl + "/api/reports");
            HttpURLConnection c = (HttpURLConnection) u.openConnection();
            c.setConnectTimeout(5000);
            c.setReadTimeout(10000);
            c.setRequestProperty("Accept", "application/json");
            int code = c.getResponseCode();
            if (code != 200) throw new IOException("HTTP " + code);

            String body = readAll(c.getInputStream());
            c.disconnect();
            JSONObject root = new JSONObject(body);
            JSONArray arr = root.getJSONArray("reports");

            // 每期存为自包含 HTML + 精简索引
            File dir = new File(getFilesDir(), "reports");
            if (!dir.exists() && !dir.mkdirs()) throw new IOException("no dir");
            JSONArray slim = new JSONArray();
            Set<String> mergedRead = new HashSet<>(readDates);
            List<ReportItem> fresh = new ArrayList<>();
            for (int i = 0; i < arr.length(); i++) {
                JSONObject o = arr.getJSONObject(i);
                String d = o.getString("date");
                String html = o.optString("html", "");
                if (!html.isEmpty()) {
                    String page = wrapPage(d, html,
                            o.isNull("newer") ? "" : o.optString("newer", ""),
                            o.isNull("older") ? "" : o.optString("older", ""));
                    writeString(new File(dir, d + ".html"), page);
                }
                if (o.optBoolean("is_read", false)) mergedRead.add(d);
                JSONObject s = new JSONObject();
                s.put("date", d);
                s.put("summary", o.optString("summary", ""));
                JSONObject stats = o.optJSONObject("stats");
                s.put("stats", stats != null ? stats : new JSONObject());
                s.put("newer", o.isNull("newer") ? JSONObject.NULL : o.optString("newer", ""));
                s.put("older", o.isNull("older") ? JSONObject.NULL : o.optString("older", ""));
                slim.put(s);
                fresh.add(fromJson(s));
            }

            JSONObject idx = new JSONObject();
            idx.put("reports", slim);
            writeString(new File(getFilesDir(), "index.json"), idx.toString());

            // 合并已读状态（电脑+手机）并刷新列表
            readDates.clear();
            readDates.addAll(mergedRead);
            saveReadPrefs();
            items.clear();
            items.addAll(fresh);
            sortItems();
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** 上报已读（fire-and-forget，失败不影响）。 */
    private void postReadToServer(final String date) {
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    URL u = new URL(serverUrl + "/api/read/" + date);
                    HttpURLConnection c = (HttpURLConnection) u.openConnection();
                    c.setRequestMethod("POST");
                    c.setConnectTimeout(3000);
                    c.setReadTimeout(3000);
                    c.getResponseCode();
                    c.disconnect();
                } catch (Exception ignored) { }
            }
        }).start();
    }

    // ------------------------------------------------------------------
    // 设置
    // ------------------------------------------------------------------

    private void showSettings() {
        final EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setText(serverUrl);
        input.setSelectAllOnFocus(true);
        new AlertDialog.Builder(this)
                .setTitle(R.string.settings_title)
                .setMessage(R.string.settings_msg)
                .setView(input)
                .setPositiveButton(R.string.settings_save, new android.content.DialogInterface.OnClickListener() {
                    @Override public void onClick(android.content.DialogInterface d, int w) {
                        String v = input.getText().toString().trim();
                        if (v.isEmpty()) return;
                        if (!v.startsWith("http://") && !v.startsWith("https://")) v = "http://" + v;
                        while (v.endsWith("/")) v = v.substring(0, v.length() - 1);
                        serverUrl = v;
                        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                                .putString(KEY_SERVER, v).apply();
                        doSync();
                    }
                })
                .setNegativeButton(R.string.settings_cancel, null)
                .show();
    }

    // ------------------------------------------------------------------
    // 工具
    // ------------------------------------------------------------------

    /** 把电脑端返回的 HTML 组装成自包含页面（与打包版一致）。 */
    private String wrapPage(String date, String html, String newer, String older) {
        String css;
        try { css = readAssetString("app.css"); } catch (IOException e) { css = ""; }
        String navPrev = newer.isEmpty()
                ? "<a></a>"
                : "<a href=\"airiradar://daily/" + newer + "\">‹ " + newer + "</a>";
        String navNext = older.isEmpty()
                ? "<a></a>"
                : "<a href=\"airiradar://daily/" + older + "\">" + older + " ›</a>";
        return "<!DOCTYPE html>\n<html lang=\"zh\"><head><meta charset=\"utf-8\">\n"
                + "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, maximum-scale=3\">\n"
                + "<title>AI信息雷达 · " + date + "</title>\n"
                + "<style>" + css + "</style></head>\n<body>\n"
                + "<header class=\"app-head\"><span class=\"app-title\">📡 AI信息雷达</span>"
                + "<span class=\"app-date\">" + date + "</span></header>\n"
                + "<article class=\"daily-content\">\n" + html + "\n</article>\n"
                + "<nav class=\"reader-nav\">" + navPrev + navNext + "</nav>\n"
                + "<footer class=\"app-foot\">AI信息雷达 · 每日AI行业资讯</footer>\n"
                + "</body></html>\n";
    }

    private void setStatus(String s) {
        statusText.setText(s);
    }

    private void saveReadPrefs() {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                .putStringSet(KEY_READ, new HashSet<String>(readDates)).apply();
    }

    private String readAssetString(String path) throws IOException {
        return readAll(getAssets().open(path));
    }

    private static String readString(File f) throws IOException {
        try (InputStream in = new FileInputStream(f)) {
            return readAll(in);
        }
    }

    private static void writeString(File f, String s) throws IOException {
        try (OutputStream out = new FileOutputStream(f)) {
            out.write(s.getBytes(StandardCharsets.UTF_8));
        }
    }

    private static String readAll(InputStream in) throws IOException {
        BufferedReader r = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = r.readLine()) != null) sb.append(line).append('\n');
        r.close();
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // 列表适配器
    // ------------------------------------------------------------------

    class ReportAdapter extends BaseAdapter {
        private final LayoutInflater inf = LayoutInflater.from(MainActivity.this);

        @Override public int getCount() { return items.size(); }
        @Override public Object getItem(int pos) { return items.get(pos); }
        @Override public long getItemId(int pos) { return pos; }

        @Override
        public View getView(int pos, View convertView, ViewGroup parent) {
            if (convertView == null) {
                convertView = inf.inflate(R.layout.item_report, parent, false);
            }
            ReportItem it = items.get(pos);

            ((TextView) convertView.findViewById(R.id.row_date)).setText(it.date);

            TextView dot = convertView.findViewById(R.id.row_dot);
            dot.setVisibility(readDates.contains(it.date) ? View.GONE : View.VISIBLE);

            TextView badge = convertView.findViewById(R.id.row_a);
            if (it.aLevel > 0) {
                badge.setText("A级" + it.aLevel);
                badge.setVisibility(View.VISIBLE);
            } else {
                badge.setVisibility(View.GONE);
            }

            ((TextView) convertView.findViewById(R.id.row_summary)).setText(it.summary);
            ((TextView) convertView.findViewById(R.id.row_stats)).setText(
                    "事件" + it.events + " · 模型" + it.models + " · 机会" + it.chances);
            return convertView;
        }
    }
}
