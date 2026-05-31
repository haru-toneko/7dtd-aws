using System;
using System.Collections.Generic;
using System.Reflection;
using System.Reflection.Emit;
using System.Threading;
using HarmonyLib;
using UnityEngine;

public class ULVersionFix : IModApi
{
    const string UL_VERSION = "2.6.17";
    static int s_ulKey = 17;
    static bool s_injecting = false;
    static Type s_gameInfoStringType;
    static int s_dummyCount = 0;

    public void InitMod(Mod _modInstance)
    {
        Debug.Log("[ULVersionFix] InitMod v12");
        var harmony = new Harmony("fix.ul.version");

        // ── 1. GameInfoString 型を取得 ─────────────────────────────────────────
        try
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                s_gameInfoStringType = asm.GetType("GameInfoString");
                if (s_gameInfoStringType != null) break;
            }
            Debug.Log("[ULVersionFix] GameInfoString: " + (s_gameInfoStringType != null ? "found" : "NOT found"));
        }
        catch (Exception ex) { Debug.LogError("[ULVersionFix] #1 failed: " + ex.Message); }

        // ── 2. gameVersion フィールドを設定 ────────────────────────────────────
        try
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                var t1 = asm.GetType("H_ModVersion+ULM_MainMenuMono_Start");
                if (t1 == null) continue;
                var f = t1.GetField("gameVersion", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                if (f != null && string.IsNullOrEmpty(f.GetValue(null) as string))
                {
                    f.SetValue(null, UL_VERSION);
                    Debug.Log("[ULVersionFix] gameVersion set to " + UL_VERSION);
                }
                break;
            }
        }
        catch (Exception ex) { Debug.LogError("[ULVersionFix] #2 failed: " + ex.Message); }

        // ── 3. get_UndeadLegacyVersion をパッチ ────────────────────────────────
        try
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                var t2 = asm.GetType("H_OptionsInfo");
                if (t2 == null) continue;
                var m = t2.GetMethod("get_UndeadLegacyVersion",
                    BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                if (m != null)
                {
                    var tr = typeof(ULVersionFix).GetMethod("VersionTranspiler", BindingFlags.Static | BindingFlags.Public);
                    harmony.Patch(m, transpiler: new HarmonyMethod(tr));
                    Debug.Log("[ULVersionFix] Patched get_UndeadLegacyVersion -> key " + s_ulKey);
                }
                break;
            }
        }
        catch (Exception ex) { Debug.LogError("[ULVersionFix] #3 failed: " + ex.Message); }

        // ── 4. GameServerInfo.SetValue をパッチ ────────────────────────────────
        try
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                var gsiType = asm.GetType("GameServerInfo");
                if (gsiType == null) continue;
                foreach (var m in gsiType.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.NonPublic))
                {
                    if (m.Name != "SetValue") continue;
                    var parms = m.GetParameters();
                    if (parms.Length == 2 && parms[0].ParameterType.Name == "GameInfoString" && parms[1].ParameterType == typeof(string))
                    {
                        var post = typeof(ULVersionFix).GetMethod("SetValuePostfix", BindingFlags.Static | BindingFlags.Public);
                        harmony.Patch(m, postfix: new HarmonyMethod(post));
                        Debug.Log("[ULVersionFix] Patched GameServerInfo.SetValue");
                        break;
                    }
                }
                break;
            }
        }
        catch (Exception ex) { Debug.LogError("[ULVersionFix] #4 failed: " + ex.Message); }

        // ── 5. NetPackageIdMapping をパッチ ────────────────────────────────────
        try
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                var npmType = asm.GetType("NetPackageIdMapping");
                if (npmType == null) continue;

                // Setup postfix: null フィールドをプレースホルダーで補完
                bool setupPatched = false;
                foreach (var candidate in new[] { "Setup", "Init", "Awake" })
                {
                    var setupM = npmType.GetMethod(candidate,
                        BindingFlags.Public | BindingFlags.Instance | BindingFlags.NonPublic);
                    if (setupM == null) continue;
                    harmony.Patch(setupM, postfix: new HarmonyMethod(
                        typeof(ULVersionFix).GetMethod("NpmSetupPostfix", BindingFlags.Static | BindingFlags.Public)));
                    Debug.Log("[ULVersionFix] Patched NetPackageIdMapping." + candidate);
                    setupPatched = true;
                    break;
                }
                if (!setupPatched)
                {
                    foreach (var ctor in npmType.GetConstructors(
                        BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
                    {
                        if (ctor.GetParameters().Length == 0) continue;
                        harmony.Patch(ctor, postfix: new HarmonyMethod(
                            typeof(ULVersionFix).GetMethod("NpmSetupPostfix", BindingFlags.Static | BindingFlags.Public)));
                        Debug.Log("[ULVersionFix] Patched NetPackageIdMapping ctor");
                    }
                }

                // GetLength prefix: null フィールドで例外が出ても 0 を返す安全網
                var getLen = npmType.GetMethod("GetLength",
                    BindingFlags.Public | BindingFlags.Instance | BindingFlags.NonPublic);
                if (getLen != null)
                {
                    harmony.Patch(getLen, prefix: new HarmonyMethod(
                        typeof(ULVersionFix).GetMethod("NpmGetLengthPrefix", BindingFlags.Static | BindingFlags.Public)));
                    Debug.Log("[ULVersionFix] Patched NetPackageIdMapping.GetLength");
                }
                break;
            }
        }
        catch (Exception ex) { Debug.LogError("[ULVersionFix] #5 failed: " + ex.Message); }

        Debug.Log("[ULVersionFix] InitMod complete");
    }

    static bool NpmHasNullFields(object inst)
    {
        try
        {
            var t = inst.GetType();
            var nameF = t.GetField("name", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            var dataF = t.GetField("data", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            return nameF?.GetValue(inst) == null || dataF?.GetValue(inst) == null;
        }
        catch { return true; }
    }

    public static void NpmSetupPostfix(object __instance)
    {
        try
        {
            var t = __instance.GetType();
            var nameF = t.GetField("name", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            var dataF = t.GetField("data", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            if (nameF == null || dataF == null) return;

            bool nameNull = nameF.GetValue(__instance) == null;
            bool dataNull = dataF.GetValue(__instance) == null;
            if (!nameNull && !dataNull) return;

            if (nameNull)
                nameF.SetValue(__instance, "UL_Placeholder_" + Interlocked.Increment(ref s_dummyCount));
            if (dataNull)
                dataF.SetValue(__instance, new byte[0]);
            Debug.Log("[ULVersionFix] NpmSetup: filled null (name=" + nameNull + " data=" + dataNull + ")");
        }
        catch (Exception ex) { Debug.LogError("[ULVersionFix] NpmSetupPostfix: " + ex.Message); }
    }

    public static bool NpmGetLengthPrefix(object __instance, ref int __result)
    {
        if (NpmHasNullFields(__instance))
        {
            __result = 0;
            return false;
        }
        return true;
    }

    public static void SetValuePostfix(object __instance, object _key, string _value)
    {
        if (s_injecting || s_gameInfoStringType == null) return;
        int k;
        try { k = Convert.ToInt32(_key); } catch { return; }
        if (k == s_ulKey) return;
        try
        {
            var getValueM = __instance.GetType().GetMethod("GetValue", new Type[] { s_gameInfoStringType });
            if (getValueM == null) return;
            var key17 = Enum.ToObject(s_gameInfoStringType, s_ulKey);
            var cur = getValueM.Invoke(__instance, new object[] { key17 }) as string;
            if (!string.IsNullOrEmpty(cur)) return;
            s_injecting = true;
            var setValueM = __instance.GetType().GetMethod("SetValue", new Type[] { s_gameInfoStringType, typeof(string) });
            if (setValueM != null)
            {
                setValueM.Invoke(__instance, new object[] { key17, UL_VERSION });
                Debug.Log("[ULVersionFix] Injected SetValue(17, " + UL_VERSION + ")");
            }
        }
        catch (Exception ex) { Debug.LogError("[ULVersionFix] SetValuePostfix: " + ex.Message); }
        finally { s_injecting = false; }
    }

    public static object CreateKey(Type t) => Enum.ToObject(t, s_ulKey);

    public static IEnumerable<CodeInstruction> VersionTranspiler(
        IEnumerable<CodeInstruction> instructions, MethodBase original)
    {
        Type retType = ((MethodInfo)original).ReturnType;
        MethodInfo helper = typeof(ULVersionFix).GetMethod("CreateKey", BindingFlags.Static | BindingFlags.Public);
        MethodInfo getTypeH = typeof(Type).GetMethod("GetTypeFromHandle", new Type[] { typeof(RuntimeTypeHandle) });
        yield return new CodeInstruction(OpCodes.Ldtoken, retType);
        yield return new CodeInstruction(OpCodes.Call, getTypeH);
        yield return new CodeInstruction(OpCodes.Call, helper);
        yield return new CodeInstruction(OpCodes.Unbox_Any, retType);
        yield return new CodeInstruction(OpCodes.Ret);
    }
}
