package com.airiradar.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.File;
import java.io.IOException;

/**
 * 阅读页：打开一期的离线 HTML（本地文件，无需联网）。
 * 拦截 airiradar://daily/<date> 实现上一篇/下一篇；http(s) 链接用外部浏览器打开。
 */
public class ReaderActivity extends Activity {

    private WebView webView;
    private LinearLayout errorView;
    private TextView errorText;
    private Button btnRetry;
    private TextView titleDate;
    private String date;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_reader);

        date = getIntent().getStringExtra("date");
        if (date == null) date = "";

        webView = findViewById(R.id.webview);
        errorView = findViewById(R.id.error_view);
        errorText = findViewById(R.id.error_text);
        btnRetry = findViewById(R.id.btn_retry);
        titleDate = findViewById(R.id.title_date);
        titleDate.setText(date);

        WebSettings ws = webView.getSettings();
        ws.setJavaScriptEnabled(true);          // 页面内链接拦截需要
        ws.setDomStorageEnabled(true);
        ws.setAllowFileAccess(true);
        ws.setLoadWithOverviewMode(true);
        ws.setUseWideViewPort(true);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                errorView.setVisibility(View.GONE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                errorView.setVisibility(View.GONE);
            }

            @Override
            public void onReceivedError(WebView view, int errorCode,
                                        String description, String failingUrl) {
                if (failingUrl != null && failingUrl.startsWith("file://")) {
                    showError(getString(R.string.err_missing));
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                // 上一篇/下一篇导航
                if (url.startsWith("airiradar://daily/")) {
                    loadDate(url.substring("airiradar://daily/".length()));
                    return true;
                }
                // 日报内的学习链接等，交给外部浏览器
                if (url.startsWith("http://") || url.startsWith("https://")) {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                    } catch (Exception ignored) { }
                    return true;
                }
                return false;
            }
        });

        findViewById(R.id.btn_back).setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { finish(); }
        });
        btnRetry.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { loadDate(date); }
        });

        loadDate(date);
    }

    /** 加载指定日期的离线 HTML：优先同步缓存，其次打包资源。 */
    private void loadDate(String d) {
        if (d == null || d.isEmpty()) return;
        date = d;
        titleDate.setText(d);
        String url = resolveReportUrl(d);
        if (url == null) {
            showError(getString(R.string.err_missing));
            return;
        }
        errorView.setVisibility(View.GONE);
        webView.loadUrl(url);
    }

    private void showError(String msg) {
        errorText.setText(msg);
        errorView.setVisibility(View.VISIBLE);
    }

    /** 返回本地 HTML 的 file:// 地址；两处都没有返回 null。 */
    private String resolveReportUrl(String d) {
        File synced = new File(getFilesDir(), "reports/" + d + ".html");
        if (synced.exists()) {
            return synced.toURI().toString();
        }
        try {
            getAssets().open("reports/" + d + ".html").close();
            return "file:///android_asset/reports/" + d + ".html";
        } catch (IOException e) {
            return null;
        }
    }

    @Override
    public void onBackPressed() {
        // 优先返回网页历史，回到本页后再退出
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
