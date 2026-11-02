Shader "GreyboxArt/Ground"
{
    Properties
    {
        _BaseColor("Base color",Color)=(.35,.4,.2,1)
        _SecondaryColor("Secondary color",Color)=(.15,.25,.08,1)
        _BaseMap("Color texture (sRGB)",2D)="white"{}
        _SecondaryMap("Secondary texture (sRGB)",2D)="white"{}
        _BlendMask("Blend mask (linear)",2D)="gray"{}
        _UseMask("Use mask",Float)=0
        _TileScale("World repeats/metre",Float)=1
        _BlendScale("Blend scale",Float)=.1
    }
    SubShader
    {
        Tags {"RenderType"="Opaque" "RenderPipeline"="UniversalPipeline"}
        Pass
        {
            Tags {"LightMode"="UniversalForward"}
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE _MAIN_LIGHT_SHADOWS_SCREEN
            #pragma multi_compile _ _SHADOWS_SOFT
            #pragma multi_compile_fog
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            TEXTURE2D(_BaseMap);SAMPLER(sampler_BaseMap);
            TEXTURE2D(_SecondaryMap);SAMPLER(sampler_SecondaryMap);
            TEXTURE2D(_BlendMask);SAMPLER(sampler_BlendMask);
            CBUFFER_START(UnityPerMaterial)
            half4 _BaseColor,_SecondaryColor;float _TileScale,_BlendScale,_UseMask;
            CBUFFER_END
            struct A{float4 positionOS:POSITION;float3 normalOS:NORMAL;float2 uv:TEXCOORD0;};
            struct V{float4 positionCS:SV_POSITION;float3 world:TEXCOORD0;half3 normal:TEXCOORD1;float2 uv:TEXCOORD2;half fog:TEXCOORD3;};
            V vert(A i){V o;o.world=TransformObjectToWorld(i.positionOS.xyz);o.positionCS=TransformWorldToHClip(o.world);o.normal=TransformObjectToWorldNormal(i.normalOS);o.uv=i.uv;o.fog=ComputeFogFactor(o.positionCS.z);return o;}
            half4 frag(V i):SV_Target
            {
                float2 uv=i.world.xz*_TileScale;
                float blend=_UseMask>.5?SAMPLE_TEXTURE2D(_BlendMask,sampler_BlendMask,i.uv).r:smoothstep(-.5,.5,sin(i.world.x*_BlendScale*3.7)+sin(i.world.z*_BlendScale*4.3));
                half3 albedo=lerp(SAMPLE_TEXTURE2D(_BaseMap,sampler_BaseMap,uv).rgb*_BaseColor.rgb,SAMPLE_TEXTURE2D(_SecondaryMap,sampler_SecondaryMap,uv).rgb*_SecondaryColor.rgb,blend);
                Light light=GetMainLight(TransformWorldToShadowCoord(i.world));half3 normal=normalize(i.normal);
                half3 color=albedo*(SampleSH(normal)+light.color*saturate(dot(normal,light.direction))*light.shadowAttenuation*light.distanceAttenuation);
                return half4(MixFog(color,i.fog),1);
            }
            ENDHLSL
        }
        UsePass "Universal Render Pipeline/Lit/ShadowCaster"
        UsePass "Universal Render Pipeline/Lit/DepthOnly"
    }
}
