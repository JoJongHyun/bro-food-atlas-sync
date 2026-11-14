package com.bro.cinemafocus;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Message;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.content.res.Configuration;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.io.ByteArrayInputStream;
import java.util.Locale;

/** Opens the content provider's original page top-level; never copies or decrypts streams. */
public final class MainActivity extends Activity {
    private static final String HOME="https://bro-cinema-hls.onrender.com/";
    private FrameLayout root, fullscreenHost;
    private LinearLayout viewerPanel;
    private WebView catalog, viewer;
    private Button focusButton;
    private LinearLayout episodeBox;
    private TextView seriesLabel;
    private final ArrayList<String> episodeUrls=new ArrayList<>();
    private final ArrayList<String> episodeLabels=new ArrayList<>();
    private int playingEpisode=-1;
    private boolean focusEnabled=true;
    private View fullscreenView;
    private WebChromeClient.CustomViewCallback fullscreenCallback;

    private int dp(int n){return (int)(getResources().getDisplayMetrics().density*n+0.5f);}
    private boolean isTvwiki(String address){
        try{
            Uri u=Uri.parse(address);
            String host=u.getHost();
            return "https".equalsIgnoreCase(u.getScheme())&&("tvwiki60.net".equals(host)||"tvwiki59.net".equals(host));
        }catch(Exception e){return false;}
    }
    private boolean isSourceEpisode(String address){
        if(!isTvwiki(address))return false;
        try{
            String path=Uri.parse(address).getPath();
            return path!=null&&path.matches("^/(?:drama|old_drama|movie|kor_movie)/[0-9]+(?:/[0-9]+)?$");
        }catch(Exception e){return false;}
    }
    private boolean isNativeLink(String address){
        try{
            Uri u=Uri.parse(address);
            return "https".equals(u.getScheme())&&"bro-cinema-hls.onrender.com".equals(u.getHost())&&"/__native_watch".equals(u.getPath());
        }catch(Exception e){return false;}
    }
    private boolean isAllowedView(String address){
        try{
            Uri u=Uri.parse(address);
            if(!"https".equalsIgnoreCase(u.getScheme()))return false;
            String h=u.getHost();
            if(h==null)return false;
            h=h.toLowerCase(Locale.ROOT);
            return isTvwiki(address)||h.equals("bunny-video.com")||h.endsWith(".bunny-cdn-player.online")||
                   h.equals("playvod.imbc.com")||h.equals("deep.wavve.com");
        }catch(Exception e){return false;}
    }
    private String normalizedLink(String link){
        try{
            if(link.startsWith("intent://")){
                Intent i=Intent.parseUri(link,Intent.URI_INTENT_SCHEME);
                Uri data=i.getData();
                return data==null?"":data.toString();
            }
            return link;
        }catch(Exception e){return "";}
    }
    private boolean blockedAd(Uri uri){
        if(uri==null||uri.getHost()==null)return false;
        String h=uri.getHost().toLowerCase(Locale.ROOT);
        return h.equals("whoas.xyz")||h.endsWith(".whoas.xyz")||
               h.equals("danf-0010.com")||h.equals("cba-111.com")||
               h.equals("googleads.g.doubleclick.net")||
               h.equals("pagead2.googlesyndication.com")||
               h.equals("www.googletagmanager.com");
    }
    private Button tool(String label,Runnable click){
        Button b=new Button(this);
        b.setText(label);b.setTextSize(12);b.setAllCaps(false);b.setTextColor(Color.WHITE);
        b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Color.rgb(31,47,73)));
        b.setOnClickListener(v->click.run());
        return b;
    }
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);
        getWindow().setStatusBarColor(Color.rgb(15,25,43));
        getWindow().setNavigationBarColor(Color.rgb(15,25,43));
        root=new FrameLayout(this);
        setContentView(root);

        catalog=makeWebView(false);
        root.addView(catalog,new FrameLayout.LayoutParams(-1,-1));
        viewerPanel=new LinearLayout(this);
        viewerPanel.setOrientation(LinearLayout.VERTICAL);
        viewerPanel.setBackgroundColor(Color.BLACK);
        viewerPanel.setVisibility(View.GONE);
        root.addView(viewerPanel,new FrameLayout.LayoutParams(-1,-1));

        LinearLayout bar=new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(Color.rgb(16,27,46));
        viewerPanel.addView(bar,new LinearLayout.LayoutParams(-1,dp(56)));
        bar.addView(tool("← BRO",this::leaveViewer),new LinearLayout.LayoutParams(0,-1,1.1f));
        viewer=makeWebView(true);
        bar.addView(tool("새로고침",()->viewer.reload()),new LinearLayout.LayoutParams(0,-1,1f));
        focusButton=tool("영상만 보기 ✓",this::toggleFocus);
        bar.addView(focusButton,new LinearLayout.LayoutParams(0,-1,1.7f));
        viewer.setVerticalScrollBarEnabled(false);
        viewer.setHorizontalScrollBarEnabled(false);
        viewerPanel.addView(viewer,new LinearLayout.LayoutParams(-1,dp(210)));
        seriesLabel=new TextView(this);
        seriesLabel.setTextColor(Color.rgb(227,238,255));seriesLabel.setTextSize(15);seriesLabel.setText("회차 선택");
        seriesLabel.setPadding(dp(16),dp(14),dp(16),dp(8));
        seriesLabel.setBackgroundColor(Color.rgb(16,27,46));
        viewerPanel.addView(seriesLabel,new LinearLayout.LayoutParams(-1,dp(53)));
        ScrollView scroll=new ScrollView(this);
        scroll.setFillViewport(true);scroll.setBackgroundColor(Color.rgb(13,23,40));
        episodeBox=new LinearLayout(this);episodeBox.setOrientation(LinearLayout.VERTICAL);
        episodeBox.setPadding(dp(10),dp(6),dp(10),dp(20));
        scroll.addView(episodeBox,new ScrollView.LayoutParams(-1,-2));
        viewerPanel.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        resizeViewer();
        fullscreenHost=new FrameLayout(this);
        fullscreenHost.setBackgroundColor(Color.BLACK);fullscreenHost.setVisibility(View.GONE);
        root.addView(fullscreenHost,new FrameLayout.LayoutParams(-1,-1));
        catalog.loadUrl(HOME);
    }
    private void resizeViewer(){
        if(viewer==null)return;
        int fullWidth=getResources().getDisplayMetrics().widthPixels;
        int maxHeight=getResources().getDisplayMetrics().heightPixels-dp(180);
        int h=Math.max(dp(130),Math.min(fullWidth*9/16,maxHeight));
        viewer.getLayoutParams().height=h;
        viewer.requestLayout();
    }
    @Override public void onConfigurationChanged(Configuration config){
        super.onConfigurationChanged(config);
        resizeViewer();
    }
    private void displayNativeEpisodes(){
        episodeBox.removeAllViews();
        if(episodeUrls.isEmpty()){
            seriesLabel.setText("BRO CINEMA · 원본 영상 화면");
            return;
        }
        for(int i=0;i<episodeUrls.size();i+=3){
            LinearLayout row=new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            for(int j=0;j<3;j++){
                final int index=i+j;
                if(index>=episodeUrls.size()){
                    View spacer=new View(this);
                    row.addView(spacer,new LinearLayout.LayoutParams(0,dp(47),1));continue;
                }
                Button b=tool(episodeLabels.get(index),()->openEpisode(index));
                b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(index==playingEpisode?Color.rgb(58,106,235):Color.rgb(34,49,78)));
                LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,dp(47),1);
                p.setMargins(dp(3),dp(3),dp(3),dp(3));
                row.addView(b,p);
            }
            episodeBox.addView(row,new LinearLayout.LayoutParams(-1,-2));
        }
    }
    private void openEpisode(int i){
        if(i<0||i>=episodeUrls.size())return;
        String url=episodeUrls.get(i);
        if(!isSourceEpisode(url))return;
        playingEpisode=i;
        displayNativeEpisodes();
        viewer.loadUrl(url);
    }
    private void openNativeWatch(Uri route){
        try{
            final String url=route.getQueryParameter("episode");
            final String title=route.getQueryParameter("title");
            final String raw=route.getQueryParameter("items");
            if(url==null||!isSourceEpisode(url)||raw==null||raw.length()>22000)return;
            JSONArray data=new JSONArray(raw);
            if(data.length()>100)return;
            episodeUrls.clear();episodeLabels.clear();
            int active=-1;
            for(int i=0;i<data.length();i++){
                JSONObject ep=data.optJSONObject(i);if(ep==null)continue;
                String link=ep.optString("url","");
                if(!isSourceEpisode(link))continue;
                String label=ep.optString("label","회차").trim();
                if(label.length()>24)label=label.substring(0,24);
                if(link.equals(url))active=episodeUrls.size();
                episodeUrls.add(link);episodeLabels.add(label);
            }
            if(episodeUrls.isEmpty()){episodeUrls.add(url);episodeLabels.add("영상 보기");active=0;}
            if(active<0)active=0;
            final String safeTitle=title==null?"작품":title.substring(0,Math.min(50,title.length()));
            seriesLabel.setText(safeTitle+" · 회차 선택");
            viewerPanel.setVisibility(View.VISIBLE);
            resizeViewer();
            openEpisode(active);
        }catch(Exception ignored){}
    }
    private void toggleFocus(){
        focusEnabled=!focusEnabled;
        focusButton.setText(focusEnabled?"영상만 보기 ✓":"원본 전체 화면");
        viewer.reload();
    }
    private WebView makeWebView(boolean playback){
        WebView w=new WebView(this);
        w.setBackgroundColor(Color.BLACK);
        WebSettings s=w.getSettings();
        s.setJavaScriptEnabled(true);s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setSupportMultipleWindows(true);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setLoadWithOverviewMode(true);s.setUseWideViewPort(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setUserAgentString(s.getUserAgentString()+" BroCinemaFocus/1.0");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(w,true);

        w.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
                if(!request.isForMainFrame())return false;
                String target=normalizedLink(request.getUrl().toString());
                if(playback){
                    if(blockedAd(Uri.parse(target)))return true;
                    return !isAllowedView(target);
                }
                if(isNativeLink(target)){
                    openNativeWatch(Uri.parse(target));
                    return true;
                }
                if(isAllowedView(target)){openViewer(target);return true;}
                return !target.startsWith(HOME);
            }
            @Override public void onPageFinished(WebView view,String url){
                if(playback&&focusEnabled&&isTvwiki(url)){
                    view.postDelayed(()->focusPlayer(view),550);
                    view.postDelayed(()->focusPlayer(view),1600);
                }
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest req){
                if(playback&&blockedAd(req.getUrl())){
                    return new WebResourceResponse("text/plain","UTF-8",204,"No Content",
                            java.util.Collections.emptyMap(),new ByteArrayInputStream(new byte[0]));
                }
                return null;
            }
        });
        w.setWebChromeClient(new WebChromeClient(){
            @Override public boolean onCreateWindow(WebView origin,boolean dialog,boolean userGesture,Message msg){
                if(!userGesture)return false;
                WebView bridge=new WebView(MainActivity.this);
                bridge.setWebViewClient(new WebViewClient(){
                    boolean handled;
                    private void open(String address){
                        if(handled)return;
                        String target=normalizedLink(address);
                        if(!isAllowedView(target))return;
                        handled=true;
                        runOnUiThread(()->openViewer(target));
                        bridge.postDelayed(bridge::destroy,500);
                    }
                    @Override public void onPageStarted(WebView v,String url,android.graphics.Bitmap icon){open(url);}
                    @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest req){
                        open(req.getUrl().toString());return true;
                    }
                });
                WebView.WebViewTransport transport=(WebView.WebViewTransport)msg.obj;
                transport.setWebView(bridge);
                msg.sendToTarget();
                return true;
            }
            @Override public void onShowCustomView(View v,CustomViewCallback cb){
                if(fullscreenView!=null){cb.onCustomViewHidden();return;}
                fullscreenView=v;fullscreenCallback=cb;
                fullscreenHost.removeAllViews();
                fullscreenHost.addView(v,new FrameLayout.LayoutParams(-1,-1));
                fullscreenHost.setVisibility(View.VISIBLE);
                getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
                setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
            }
            @Override public void onHideCustomView(){hideFullscreen();}
        });
        return w;
    }
    private void focusPlayer(WebView page){
        if(!focusEnabled||!isTvwiki(page.getUrl()))return;
        String js="(function(){var p=document.getElementById('playerArea');if(!p)return;"+
                "var n=p;while(n&&n!==document.body){var par=n.parentElement;if(!par)break;"+
                "Array.from(par.children).forEach(function(s){if(s!==n)s.style.setProperty('display','none','important');});n=par;}"+
                "document.documentElement.style.setProperty('background','#000','important');"+
                "document.body.style.setProperty('margin','0','important');"+
                "document.body.style.setProperty('overflow','hidden','important');"+
                "p.style.setProperty('display','block','important');"+
                "p.style.setProperty('position','fixed','important');p.style.setProperty('inset','0','important');"+
                "p.style.setProperty('height','100dvh','important');p.style.setProperty('width','100vw','important');"+
                "p.style.setProperty('z-index','99999','important');p.style.setProperty('background','#000','important');"+
                "var e=p.querySelector('.embed-container');if(e){e.style.setProperty('height','100%','important');"+
                "e.style.setProperty('width','100%','important');}"+
                "var f=p.querySelector('iframe');if(f){f.style.setProperty('height','100%','important');"+
                "f.style.setProperty('width','100%','important');}return true})()";
        page.evaluateJavascript(js,null);
    }
    private void openViewer(String url){
        if(!isAllowedView(url))return;
        episodeUrls.clear();episodeLabels.clear();playingEpisode=-1;
        displayNativeEpisodes();
        viewerPanel.setVisibility(View.VISIBLE);
        resizeViewer();
        viewer.loadUrl(url);
    }
    private void leaveViewer(){
        episodeUrls.clear();episodeLabels.clear();playingEpisode=-1;
        displayNativeEpisodes();
        if(fullscreenView!=null)hideFullscreen();
        viewer.loadUrl("about:blank");
        viewerPanel.setVisibility(View.GONE);
    }
    private void hideFullscreen(){
        if(fullscreenView==null)return;
        fullscreenHost.removeAllViews();fullscreenHost.setVisibility(View.GONE);
        fullscreenView=null;
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
        if(fullscreenCallback!=null)fullscreenCallback.onCustomViewHidden();
        fullscreenCallback=null;
    }
    @Override public void onBackPressed(){
        if(fullscreenView!=null)hideFullscreen();
        else if(viewerPanel.getVisibility()==View.VISIBLE){
            if(viewer.canGoBack())viewer.goBack();else leaveViewer();
        }else if(catalog.canGoBack())catalog.goBack();
        else super.onBackPressed();
    }
    @Override protected void onDestroy(){
        if(viewer!=null)viewer.destroy();
        if(catalog!=null)catalog.destroy();
        super.onDestroy();
    }
}
