using UnityEngine;

public class CoinRotate : MonoBehaviour
{
    [Header("Rotation")]
    public float rotateSpeed = 200f;     // speed of spin (degrees/sec)

    [Header("Floating (optional)")]
    public bool enableBob = true;        // toggle up-down motion
    public float bobHeight = 0.25f;      // how high it moves
    public float bobSpeed = 2f;          // speed of bobbing

    [Header("Auto Destroy (optional)")]
    public bool autoDestroy = false;     // destroy coin after time
    public float destroyAfter = 10f;

    private Vector3 startPos;

    void Start()
    {
        startPos = transform.position;

        if (autoDestroy)
        {
            Destroy(gameObject, destroyAfter);
        }
    }

    void Update()
    {
        // 🔄 Rotate coin (Y axis)
        transform.Rotate(0f, rotateSpeed * Time.deltaTime, 0f, Space.World);

        // 🌊 Bob up and down (optional)
        if (enableBob)
        {
            float newY = startPos.y + Mathf.Sin(Time.time * bobSpeed) * bobHeight;
            transform.position = new Vector3(transform.position.x, newY, transform.position.z);
        }
    }
}