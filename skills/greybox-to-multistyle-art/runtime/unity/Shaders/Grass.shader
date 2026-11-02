Shader "GreyboxArt/Grass"
{
    Properties{_BaseColor("Grass color",Color)=(.2,.45,.12,1) _Wind("Wind displacement metres",Float)=.15}
    SubShader
    {
        Tags{"RenderType"="Opaque" "RenderPipeline"="UniversalPipeline"}
        Pass
        {
            Tags{"LightMode"="UniversalForward"} Cull Off
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE
            #pragma multi_compile_fog
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            CBUFFER_START(UnityPerMaterial)
            half4 _BaseColor;float _Wind;
            CBUFFER_END
            struct A{float4 positionOS:POSITION;float3 normalOS:NORMAL;float2 uv:TEXCOORD0;UNITY_VERTEX_INPUT_INSTANCE_ID};
            struct V{float4 positionCS:SV_POSITION;float3 world:TEXCOORD0;float2 uv:TEXCOORD1;half fog:TEXCOORD2;};
            V vert(A i){UNITY_SETUP_INSTANCE_ID(i);V o;o.world=TransformObjectToWorld(i.positionOS.xyz);float phase=o.world.x*.8+o.world.z*.6+_Time.y*2;o.world.xz+=float2(sin(phase),cos(phase*.73))*_Wind*i.uv.y*i.uv.y;o.positionCS=TransformWorldToHClip(o.world);o.uv=i.uv;o.fog=ComputeFogFactor(o.positionCS.z);return o;}
            half4 frag(V i):SV_Target{Light light=GetMainLight(TransformWorldToShadowCoord(i.world));half3 color=_BaseColor.rgb*lerp(.45,1.2,i.uv.y)*(SampleSH(half3(0,1,0))+light.color*light.shadowAttenuation*.8);return half4(MixFog(color,i.fog),1);}
            ENDHLSL
        }
    }
}
