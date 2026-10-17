// AlignRunner.cs — Unity 侧对齐测试驱动 (2022.3 LTS)
// ops.json 结构: {"cases":[{"name":..., "op":..., "args":{...}}, ...]}
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class AlignRunner
{
    static Dictionary<string, GameObject> s_objs = new Dictionary<string, GameObject>();

    public static void Run()
    {
        string opsPath = GetArg("-alignOps");
        if (string.IsNullOrEmpty(opsPath) || !File.Exists(opsPath))
        {
            Debug.LogError("[Align] 缺少 -alignOps: " + opsPath);
            EditorApplication.Exit(1);
            return;
        }
        string caseDir = Path.GetDirectoryName(opsPath);
        string unityDir = Path.Combine(caseDir, "unity");
        Directory.CreateDirectory(unityDir);

        ClearScene();

        var ops = JsonUtility.FromJson<OpList>(File.ReadAllText(opsPath));
        var results = new List<string>();
        foreach (var c in ops.cases)
        {
            var a = c.args ?? new Args();
            try
            {
                Capture(unityDir, c.name + "_before.png");
                GameObject go = ExecuteOp(c.op, a);
                Capture(unityDir, c.name + "_after.png");
                // 无返回物体时 (physics_simulate 等) 按 args 指定的名字回读位姿+速度
                if (go == null && !string.IsNullOrEmpty(GetName(a)))
                    go = FindObj(GetName(a));
                string entry = "{\"name\":\"" + c.name + "\",\"ok\":true";
                if (go != null)
                {
                    var t = go.transform;
                    entry += ",\"position\":[" + F(t.position.x) + "," + F(t.position.y) + "," + F(t.position.z) + "]";
                    entry += ",\"rotation_deg\":[" + F(t.eulerAngles.x) + "," + F(t.eulerAngles.y) + "," + F(t.eulerAngles.z) + "]";
                    entry += ",\"scale\":[" + F(t.localScale.x) + "," + F(t.localScale.y) + "," + F(t.localScale.z) + "]";
                    var rb = go.GetComponent<Rigidbody>();
                    if (rb != null)
                        entry += ",\"velocity\":[" + F(rb.velocity.x) + "," + F(rb.velocity.y) + "," + F(rb.velocity.z) + "]";
                }
                entry += "}";
                results.Add(entry);
                Debug.Log("[Align] ok: " + c.name);
            }
            catch (Exception e)
            {
                try { Capture(unityDir, c.name + "_after.png"); } catch {}
                results.Add("{\"name\":\"" + c.name + "\",\"ok\":false,\"err\":\"" +
                            e.Message.Replace("\"", "'") + "\"}");
                Debug.LogError("[Align] fail: " + c.name + " -> " + e);
            }
        }
        File.WriteAllText(Path.Combine(caseDir, "unity_result.json"),
            "{\"results\":[" + string.Join(",", results) + "]}");
        Debug.Log("[Align] done: " + caseDir);
        EditorApplication.Exit(0);
    }

    static void ClearScene()
    {
        foreach (var go in UnityEngine.SceneManagement.SceneManager.GetActiveScene().GetRootGameObjects())
            if (go.name != "Main Camera" && go.name != "Directional Light")
                UnityEngine.Object.DestroyImmediate(go);
        s_objs.Clear();
    }

    // ---- 物理对拍 (2026-10-13): 硬编码用例镜像 Loom 侧 align_physics.py ----
    // 用 Physics.Simulate 确定性步进 (Physics.simulationMode=Script)。用例集与
    // Loom 侧一一对应; 输出 unity_physics_result.json 供 compare 对比。
    public static void RunPhysics()
    {
        string outPath = GetArg("-out");
        if (string.IsNullOrEmpty(outPath))
        {
            Debug.LogError("[Align] 缺少 -out");
            EditorApplication.Exit(1);
            return;
        }
        // 对齐 Loom 重力 (-9.8, Unity 默认 -9.81)
        Physics.gravity = new Vector3(0f, -9.8f, 0f);
        const float SUB_DT = 1f / 60f;
        var results = new List<string>();

        // 通用用例结构 (镜像 Loom align_physics.py 的 CASES):
        //   objs: (name, primitive, pos[3], scale[3]?, useGravity, isKinematic,
        //          velocity[3]?, restitution, friction)  rb=null 即静态碰撞体
        //   post: play 后设速度 (Loom 语义: velocity 在 play 后设才生效)
        // frames = 逻辑帧数 (Unity 跑 frames*2 个 1/60 子步)
        var cases = new object[][]
        {
            // name, objs, postVel(name->vel), frames
            new object[] {"freefall_1s",
                new object[][] {
                    new object[] {"A","cube",new float[]{0,5,0},null,true,false,null,0f,0f}},
                null, 30},
            new object[] {"no_gravity_1s",
                new object[][] {
                    new object[] {"A","cube",new float[]{0,5,0},null,false,false,null,0f,0f}},
                null, 30},
            new object[] {"kinematic_1s",
                new object[][] {
                    new object[] {"A","cube",new float[]{0,5,0},null,true,true,null,0f,0f}},
                null, 30},
            new object[] {"horizontal_1s",
                new object[][] {
                    new object[] {"A","cube",new float[]{0,5,0},null,false,false,null,0f,0f}},
                new object[] {"A", new float[]{5,0,0}}, 30},
            new object[] {"land_stop",
                new object[][] {
                    new object[] {"Ground","cube",new float[]{0,-0.25f,0},new float[]{10,0.5f,10},false,true,null,0f,0f},
                    new object[] {"A","cube",new float[]{0,5,0},null,true,false,null,0f,0f}},
                null, 60},
            new object[] {"bounce_rest07",
                new object[][] {
                    new object[] {"Ground","cube",new float[]{0,-0.25f,0},new float[]{10,0.5f,10},false,true,null,0f,0f},
                    new object[] {"A","sphere",new float[]{0,5,0},null,true,false,null,0.7f,0f}},
                null, 90},
            new object[] {"friction_slide",
                new object[][] {
                    new object[] {"Ground","cube",new float[]{0,-0.25f,0},new float[]{10,0.5f,10},false,true,null,0f,0f},
                    new object[] {"A","cube",new float[]{0,0.5f,0},null,true,false,null,0f,0.5f}},
                new object[] {"A", new float[]{5,0,0}}, 60},
        };

        foreach (var cs in cases)
        {
            string name = (string)cs[0];
            var objs = (object[][])cs[1];
            var post = (object[])cs[2];
            int frames = (int)cs[3];
            try
            {
                ClearScene();
                GameObject readGo = null;
                foreach (var od in objs)
                {
                    string onm = (string)od[0];
                    string prim = (string)od[1];
                    float[] pos = (float[])od[2];
                    float[] sc = (float[])od[3];
                    bool useG = (bool)od[4];
                    bool kin = (bool)od[5];
                    float[] v0 = (float[])od[6];
                    float rest = (float)od[7];
                    float fric = (float)od[8];
                    var go = GameObject.CreatePrimitive(
                        prim == "sphere" ? PrimitiveType.Sphere
                        : prim == "plane" ? PrimitiveType.Plane : PrimitiveType.Cube);
                    go.name = onm;
                    go.transform.position = new Vector3(pos[0], pos[1], pos[2]);
                    if (sc != null) go.transform.localScale = new Vector3(sc[0], sc[1], sc[2]);
                    if (!kin || useG || v0 != null || rest > 0 || fric > 0)
                    {
                        var rb = go.AddComponent<Rigidbody>();
                        rb.useGravity = useG;
                        rb.isKinematic = kin;
                        if (v0 != null) rb.velocity = new Vector3(v0[0], v0[1], v0[2]);
                        if (rest > 0 || fric > 0)
                        {
                            var pm = new PhysicMaterial();
                            pm.bounciness = rest;
                            pm.dynamicFriction = fric > 0 ? fric : 0.5f;
                            pm.staticFriction = fric > 0 ? fric : 0.5f;
                            // Maximum: 物体自身材质值主导 (地面用默认材质, Average
                            // 会把弹性/摩擦减半, 与 Loom 单侧参数语义不符)
                            pm.bounceCombine = PhysicMaterialCombine.Maximum;
                            pm.frictionCombine = PhysicMaterialCombine.Maximum;
                            go.GetComponent<Collider>().material = pm;
                        }
                    }
                    if (onm == "A") readGo = go;
                }
                // play 后设初速 (Loom 语义: velocity 在 play 后设)
                if (post != null)
                {
                    string pn = (string)post[0];
                    float[] pv = (float[])post[1];
                    var pgo = FindObj(pn);
                    if (pgo != null)
                    {
                        var prb = pgo.GetComponent<Rigidbody>();
                        if (prb != null) prb.velocity = new Vector3(pv[0], pv[1], pv[2]);
                    }
                }

                var oldMode = Physics.simulationMode;
                Physics.simulationMode = SimulationMode.Script;
                try
                {
                    for (int i = 0; i < frames * 2; i++)   // 逻辑帧 -> 物理子步
                        Physics.Simulate(SUB_DT);
                }
                finally { Physics.simulationMode = oldMode; }

                var t = readGo.transform;
                var rrb = readGo.GetComponent<Rigidbody>();
                string entry = "{\"name\":\"" + name + "\",\"ok\":true";
                entry += ",\"position\":[" + F(t.position.x) + "," + F(t.position.y) + "," + F(t.position.z) + "]";
                if (rrb != null)
                    entry += ",\"velocity\":[" + F(rrb.velocity.x) + "," + F(rrb.velocity.y) + "," + F(rrb.velocity.z) + "]";
                entry += "}";
                results.Add(entry);
                Debug.Log("[Align-Phys] ok: " + name);
            }
            catch (Exception e)
            {
                results.Add("{\"name\":\"" + name + "\",\"ok\":false,\"err\":\"" +
                            e.Message.Replace("\"", "'") + "\"}");
                Debug.LogError("[Align-Phys] fail: " + name + " -> " + e);
            }
        }
        File.WriteAllText(outPath,
            "{\"results\":[" + string.Join(",", results) + "]}");
        Debug.Log("[Align-Phys] done: " + outPath);
        EditorApplication.Exit(0);
    }

    // ---- 脚本行为对拍 (2026-10-13): 镜像 Loom rotate 脚本 (90°/s) ----
    // Unity Update 由 PlayerLoop 驱动, 不便确定性控制 -> 手动以固定 dt 调等价
    // 旋转逻辑 (transform.Rotate), 验证同语义脚本在两引擎得到相同角度。
    public static void RunScript()
    {
        string outPath = GetArg("-out");
        Directory.CreateDirectory(Path.GetDirectoryName(outPath));
        Physics.gravity = new Vector3(0f, -9.8f, 0f);
        var results = new List<string>();
        // 用例: rotate 90°/s, 不同逻辑帧数 (30fps -> dt=1/30)
        float speedDeg = 90f;
        float logicDt = 1f / 30f;
        foreach (int frames in new int[] { 30, 60, 120 })
        {
            ClearScene();
            var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = "A";
            go.transform.rotation = Quaternion.identity;
            // 等价脚本: 每逻辑帧绕 Y 旋转 speedDeg*logicDt 度
            for (int i = 0; i < frames; i++)
                go.transform.Rotate(0f, speedDeg * logicDt, 0f, Space.Self);
            float y = go.transform.eulerAngles.y;
            string entry = "{\"name\":\"rotate_" + frames + "\",\"ok\":true";
            entry += ",\"rot_y_deg\":" + F(y) + "}";
            results.Add(entry);
            Debug.Log("[Align-Script] rotate_" + frames + " y=" + y);
        }
        File.WriteAllText(outPath,
            "{\"results\":[" + string.Join(",", results) + "]}");
        Debug.Log("[Align-Script] done: " + outPath);
        EditorApplication.Exit(0);
    }

    static string GetName(Args a)
    {
        return !string.IsNullOrEmpty(a.name_or_id) ? a.name_or_id : a.name;
    }

    static string F(float v)
    {
        return v.ToString("0.####", System.Globalization.CultureInfo.InvariantCulture);
    }

    // 返回被操作的 GameObject (供读回 position/rotation/scale); 无则 null
    static GameObject ExecuteOp(string op, Args a)
    {
        switch (op)
        {
            case "unity_gameobject_create":
            {
                var prim = string.IsNullOrEmpty(a.primitive) ? "cube" : a.primitive;
                GameObject obj = GameObject.CreatePrimitive(PrimToType(prim));
                string nm = !string.IsNullOrEmpty(a.name) ? a.name : obj.name;
                obj.name = nm;
                s_objs[nm] = obj;
                if (a.position != null && a.position.Length == 3)
                    obj.transform.position = ToVec3(a.position);
                if (a.scale != null && a.scale.Length == 3)
                    obj.transform.localScale = ToVec3(a.scale);
                Selection.activeGameObject = obj;
                return obj;
            }
            case "unity_transform_set":
            {
                var go = FindObj(GetName(a));
                if (go == null) throw new Exception("未找到物体: " + GetName(a));
                if (a.position != null && a.position.Length == 3)
                    go.transform.position = ToVec3(a.position);
                if (a.rotation != null && a.rotation.Length == 3)
                    go.transform.eulerAngles = ToVec3(a.rotation);   // 引擎 MCP 里 rotation 是度
                if (a.scale != null && a.scale.Length == 3)
                    go.transform.localScale = ToVec3(a.scale);
                return go;
            }
            case "unity_material_set":
            {
                var go = FindObj(GetName(a));
                if (go == null) throw new Exception("未找到物体: " + GetName(a));
                var rend = go.GetComponent<Renderer>();
                if (rend == null) throw new Exception("无 Renderer");
                Color col;
                if (!string.IsNullOrEmpty(a.color) && ColorUtility.TryParseHtmlString(a.color, out col))
                    rend.sharedMaterial.color = col;
                return go;
            }
            case "unity_collider_set":
            {
                var go = FindObj(GetName(a));
                if (go == null) throw new Exception("未找到物体: " + GetName(a));
                var col = go.GetComponent<Collider>();
                if (col == null) throw new Exception("无 Collider");
                col.enabled = a.enabled;
                return go;
            }
            case "unity_rigidbody_set":
            {
                var go = FindObj(GetName(a));
                if (go == null) throw new Exception("未找到物体: " + GetName(a));
                var rb = go.GetComponent<Rigidbody>();
                if (rb == null) rb = go.AddComponent<Rigidbody>();
                rb.useGravity = a.use_gravity;
                rb.isKinematic = a.is_kinematic;
                if (a.mass > 0) rb.mass = a.mass;
                if (a.velocity != null && a.velocity.Length == 3)
                    rb.velocity = ToVec3(a.velocity);
                // 摩擦/弹性: Unity 3D 在 PhysicMaterial (对齐 Loom rb.friction/restitution)
                if (a.friction > 0 || a.restitution > 0)
                {
                    var col = go.GetComponent<Collider>();
                    if (col != null)
                    {
                        var pm = new PhysicMaterial();
                        pm.dynamicFriction = a.friction > 0 ? a.friction : 0.5f;
                        pm.staticFriction = a.friction > 0 ? a.friction : 0.5f;
                        pm.bounciness = a.restitution;
                        pm.frictionCombine = PhysicMaterialCombine.Average;
                        pm.bounceCombine = PhysicMaterialCombine.Average;
                        col.material = pm;
                    }
                }
                return go;
            }
            case "unity_physics_simulate":
            {
                // 确定性物理步进: Physics.simulationMode=Script -> 手动 Physics.Simulate
                // (Unity 官方确定性物理 API; dt=1/60 对齐 Loom 物理子步)
                var oldMode = Physics.simulationMode;
                Physics.simulationMode = SimulationMode.Script;
                try
                {
                    // ops 的 frames = 逻辑帧数 (Loom 30fps 逻辑 / 60Hz 物理子步,
                    // 每逻辑帧 2 子步) -> Unity 跑 frames*2 个 1/60s 步, 时长等价.
                    int n = a.frames > 0 ? a.frames : 60;
                    for (int i = 0; i < n * 2; i++)
                        Physics.Simulate(1f / 60f);
                }
                finally
                {
                    Physics.simulationMode = oldMode;
                }
                return null;
            }
            case "unity_light_add":
            {
                var lg = new GameObject(string.IsNullOrEmpty(a.name) ? "Light" : a.name);
                var light = lg.AddComponent<Light>();
                light.type = a.kind == "point" ? LightType.Point : LightType.Directional;
                if (a.position != null && a.position.Length == 3)
                    lg.transform.position = ToVec3(a.position);
                s_objs[lg.name] = lg;
                return lg;
            }
            case "unity_playmode_toggle":
                EditorApplication.isPlaying = a.on;
                return null;
            default:
                throw new Exception("未支持 op: " + op);
        }
    }

    static GameObject FindObj(string name)
    {
        if (string.IsNullOrEmpty(name)) return null;
        GameObject go;
        if (s_objs.TryGetValue(name, out go) && go != null) return go;
        var all = Resources.FindObjectsOfTypeAll<GameObject>();
        foreach (var g in all)
            if (g.name == name && g.scene.IsValid()) return g;
        return null;
    }

    static PrimitiveType PrimToType(string p)
    {
        if (p == "sphere") return PrimitiveType.Sphere;
        if (p == "plane") return PrimitiveType.Plane;
        return PrimitiveType.Cube;
    }

    static Vector3 ToVec3(float[] a) { return new Vector3(a[0], a[1], a[2]); }

    static void Capture(string dir, string name)
    {
        var cam = Camera.main;
        if (cam == null)
        {
            var camGo = new GameObject("AlignCam");
            cam = camGo.AddComponent<Camera>();
            camGo.transform.position = new Vector3(0, 3, -8);
            camGo.transform.LookAt(Vector3.zero);
            camGo.tag = "MainCamera";
        }
        int W = 1280, H = 800;
        var rt = new RenderTexture(W, H, 24);
        var old = cam.targetTexture;
        cam.targetTexture = rt;
        cam.Render();
        RenderTexture.active = rt;
        var tex = new Texture2D(W, H, TextureFormat.RGB24, false);
        tex.ReadPixels(new Rect(0, 0, W, H), 0, 0);
        tex.Apply();
        File.WriteAllBytes(Path.Combine(dir, name), tex.EncodeToPNG());
        cam.targetTexture = old;
        UnityEngine.Object.DestroyImmediate(rt);
        UnityEngine.Object.DestroyImmediate(tex);
    }

    static string GetArg(string key)
    {
        var a = Environment.GetCommandLineArgs();
        for (int i = 0; i < a.Length - 1; i++)
            if (a[i] == key) return a[i + 1];
        return null;
    }

    [Serializable] public class OpList { public Op[] cases; }
    [Serializable]
    public class Op
    {
        public string name;
        public string op;
        public Args args;      // ← 嵌套匹配 ops.json
    }
    [Serializable]
    public class Args
    {
        public string name;
        public string name_or_id;
        public string primitive;
        public string color;
        public string kind;
        public float[] position;
        public float[] rotation;
        public float[] scale;
        public bool enabled;
        public bool use_gravity;
        public float mass;
        public bool on;
        // 物理扩展 (2026-10-13)
        public bool is_kinematic;
        public float friction;
        public float restitution;
        public float[] velocity;
        public int frames;
    }
}
