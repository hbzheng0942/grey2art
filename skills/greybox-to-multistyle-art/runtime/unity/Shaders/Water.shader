Shader "GreyboxArt/Water"
{
    Properties
    {
        _BaseColor("Shallow color",Color)=(.05,.4,.5,.85)
        _DeepColor("Deep color",Color)=(.015,.12,.2,1)
        _NormalMap("Normal texture (linear)",2D)="bump"{}
        _ShoreMask("Shore mask (linear)",2D)="white"{}
        _UseShoreMask("Use shore mask",Float)=0
        _Speed("Flow speed",Float)=.3
        _Amplitude("Wave amplitude",Float)=.08
        _DepthDistance("Depth color distance",Float)=3
        _ShoreWidth("Shore transition metres",Float)=.3
        _Roughness("Reflection roughness",Range(0,1))=.2
    }
    SubShader
    {
        Tags {"RenderType"="Transparent" "Queue"="Transparent" "RenderPipeline"="UniversalPipeline"}
        Pass
        {
            Tags {"LightMode"="UniversalForward"}
            Blend SrcAlpha OneMinusSrcAlpha ZWrite Off Cull Off
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE
            #pragma multi_compile_fog
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DeclareDepthTexture.hlsl"
            TEXTURE2D(_NormalMap);SAMPLER(sampler_NormalMap);
            TEXTURE2D(_ShoreMask);SAMPLER(sampler_ShoreMask);
            CBUFFER_START(UnityPerMaterial)
            half4 _BaseColor,_DeepColor;float _Speed,_Amplitude,_DepthDistance,_ShoreWidth,_Roughness,_UseShoreMask;
            CBUFFER_END
            struct A{float4 positionOS:POSITION;float2 uv:TEXCOORD0;};
            struct V{float4 positionCS:SV_POSITION;float3 world:TEXCOORD0;half fog:TEXCOORD1;float2 uv:TEXCOORD2;};
            V vert(A i){V o;o.world=TransformObjectToWorld(i.positionOS.xyz);o.world.y+=sin(o.world.x*1.2+_Time.y*_Speed*2)*cos(o.world.z*.9+_Time.y*_Speed)*_Amplitude;o.positionCS=TransformWorldToHClip(o.world);o.fog=ComputeFogFactor(o.positionCS.z);o.uv=i.uv;return o;}
            half4 frag(V i):SV_Target
            {
                float2 uv=i.world.xz*.15;float time=_Time.y*_Speed*.1;
                half3 n1=UnpackNormal(SAMPLE_TEXTURE2D(_NormalMap,sampler_NormalMap,uv+float2(time,time*.4)));
                half3 n2=UnpackNormal(SAMPLE_TEXTURE2D(_NormalMap,sampler_NormalMap,uv*1.73-float2(time*.6,time)));
                half3 normal=normalize(half3(n1.x+n2.x+cos(i.world.x*1.2+_Time.y*_Speed*2)*_Amplitude,2,n1.y+n2.y));
                float2 screenUV=GetNormalizedScreenSpaceUV(i.positionCS);float sceneDepth=LinearEyeDepth(SampleSceneDepth(screenUV),_ZBufferParams);float waterDepth=-TransformWorldToView(i.world).z;float depth=max(0,sceneDepth-waterDepth);
                half3 albedo=lerp(_BaseColor.rgb,_DeepColor.rgb,saturate(depth/max(.001,_DepthDistance)));
                half3 view=GetWorldSpaceNormalizeViewDir(i.world);half fresnel=pow(1-saturate(dot(normal,view)),5);
                Light light=GetMainLight(TransformWorldToShadowCoord(i.world));half spec=pow(saturate(dot(normal,normalize(light.direction+view))),lerp(128,8,_Roughness));
                half3 reflection=GlossyEnvironmentReflection(reflect(-view,normal),i.world,_Roughness,1,screenUV);
                half3 color=albedo*(SampleSH(normal)+light.color*(.2+.8*saturate(dot(normal,light.direction)))*light.shadowAttenuation)+reflection*(.08+.7*fresnel)+light.color*spec;
                half shore=1-saturate(depth/max(.001,_ShoreWidth));color=lerp(color,half3(.75,.85,.82),shore*.25);
                half mask=_UseShoreMask>.5?SAMPLE_TEXTURE2D(_ShoreMask,sampler_ShoreMask,i.uv).r:1;clip(mask-.001);
                return half4(MixFog(color,i.fog),saturate(_BaseColor.a*saturate(depth/max(.001,_ShoreWidth))+.1*fresnel)*mask);
            }
            ENDHLSL
        }
    }
}
