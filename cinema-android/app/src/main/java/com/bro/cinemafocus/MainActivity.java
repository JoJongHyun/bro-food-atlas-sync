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
import java.io.ByteArrayInputStream;
import java.util.Locale;

/** Opens the content provider's original page top-level; never copies or decrypts streams. */
public final class MainActivity extends Activity {
    private static final String HOME="https://bro-cinema-hls.onrender.com/";
    private FrameLayout root, fullscreenHost;
    private LinearLayout viewerPanel;
    private WebView catalog, viewer;
    private Button focusButton;
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
        viewerPanel.addView(viewer,new LinearLayout.LayoutParams(-1,0,1));
        fullscreenHost=new FrameLayout(this);
        fullscreenHost.setBackgroundColor(Color.BLACK);fullscreenHost.setVisibility(View.GONE);
        root.addView(fullscreenHost,new FrameLayout.LayoutParams(-1,-1));
        catalog.loadUrl(HOME);
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
        viewerPanel.setVisibility(View.VISIBLE);
        viewer.loadUrl(url);
    }
    private void leaveViewer(){
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
