using UnityEngine;
using TMPro;
using UnityEngine.SceneManagement;

public class PlayerController3D : MonoBehaviour
{
    public float forwardSpeed = 10f;
    public float jumpForce = 7f;
    public float turnSpeed = 10f;

    public float fallMultiplier = 2.5f;
    public float lowJumpMultiplier = 2f;

    private Rigidbody rb;
    private bool isGrounded = true;
    private bool isTurning = false;
    private Vector3 targetDirection;

    // 🎯 SCORE
    public float score = 0f;
    public TextMeshProUGUI scoreText;

    // ❤️ HEALTH
    public int health = 3;
    public TextMeshProUGUI healthText;

    // 🎯 GAME OVER UI
    public GameObject gameOverPanel;

    // 🎧 AUDIO
    public AudioSource audioSource;
    public AudioClip jumpSound;
    public AudioClip turnSound;
    public AudioClip hitSound;
    public AudioClip coinpickSound;

    private bool isGameOver = false;

    private float lastHitTime = 0f;
    public float damageCooldown = 0.5f;

    // 🪙 COINS
    public int coinCount = 0;
    public TextMeshProUGUI coinText;

    // 🔥 COIN → HEALTH
    public int coinsForHealth = 20;

    // 🔥 SPEED SYSTEM
    public float speedIncreaseInterval = 100f;
    public float speedIncreaseAmount = 2f;
    private float nextSpeedMilestone = 100f;

    // 🔥 NEW: FALL DETECTION
    public float fallThreshold = -5f;

    void Start()
    {
        rb = GetComponent<Rigidbody>();
        rb.freezeRotation = true;

        targetDirection = transform.forward;

        if (gameOverPanel != null)
            gameOverPanel.SetActive(false);

        UpdateHealthUI();
    }

    void Update()
    {
        if (isGameOver) return;

        // 🎯 SCORE
        score += Time.deltaTime * 10f;
        scoreText.text = Mathf.FloorToInt(score) + " m";

        // 🚀 SPEED INCREASE
        if (score >= nextSpeedMilestone)
        {
            forwardSpeed += speedIncreaseAmount;
            nextSpeedMilestone += speedIncreaseInterval;
        }

        // 🔥 FALL CHECK (NEW)
        if (transform.position.y < fallThreshold)
        {
            Debug.Log("Player Fell → Game Over");
            GameOver();
        }

        // INPUT
        if (Input.GetKeyDown(KeyCode.A) && !isTurning) Turn(-90f);
        if (Input.GetKeyDown(KeyCode.D) && !isTurning) Turn(90f);
        if (Input.GetKeyDown(KeyCode.Space)) Jump();
    }

    public void Jump()
    {
        Debug.Log("Jump Attempt");
        if (isGrounded && !isGameOver)
        {
            Debug.Log("Jump Attempt 1");
            audioSource.PlayOneShot(jumpSound);

            rb.linearVelocity = new Vector3(
                rb.linearVelocity.x,
                jumpForce,
                rb.linearVelocity.z
            );

            isGrounded = false;
        }
    }

    public void ExternalTurn(float angle)
    {
        Debug.Log("ExternalTurn ");
        if (!isTurning && !isGameOver)
        {
            Debug.Log("ExternalTurn 1 ");
            Turn(angle);
        }
    }

    void Turn(float angle)
    {
        audioSource.PlayOneShot(turnSound);

        isTurning = true;
        targetDirection = Quaternion.Euler(0, angle, 0) * targetDirection;
    }

    void FixedUpdate()
    {
        if (isGameOver) return;

        Vector3 forwardMove = targetDirection.normalized * forwardSpeed;

        rb.linearVelocity = new Vector3(
            forwardMove.x,
            rb.linearVelocity.y,
            forwardMove.z
        );

        if (isTurning)
        {
            Quaternion targetRot = Quaternion.LookRotation(targetDirection);
            transform.rotation = Quaternion.Lerp(
                transform.rotation,
                targetRot,
                turnSpeed * Time.fixedDeltaTime
            );

            if (Quaternion.Angle(transform.rotation, targetRot) < 1f)
            {
                transform.rotation = targetRot;
                isTurning = false;
            }
        }

        transform.rotation = Quaternion.LookRotation(targetDirection);

        if (rb.linearVelocity.y < 0)
        {
            rb.linearVelocity += Vector3.up * Physics.gravity.y * (fallMultiplier - 1) * Time.fixedDeltaTime;
        }
        else if (rb.linearVelocity.y > 0 && !Input.GetKey(KeyCode.Space))
        {
            rb.linearVelocity += Vector3.up * Physics.gravity.y * (lowJumpMultiplier - 1) * Time.fixedDeltaTime;
        }

        rb.angularVelocity = Vector3.zero;
    }

    void OnCollisionEnter(Collision collision)
    {
        if (collision.gameObject.CompareTag("Ground") || collision.transform.root.CompareTag("Ground"))
        {
            isGrounded = true;
        }

        if (collision.gameObject.CompareTag("Obstacle"))
        {
            TakeDamage();
            collision.gameObject.SetActive(false);
        }
    }

    void OnTriggerEnter(Collider other)
    {
        if (other.CompareTag("Coin"))
        {
            audioSource.PlayOneShot(coinpickSound);
            CollectCoin(other.gameObject);
        }
    }

    void CollectCoin(GameObject coin)
    {
        coinCount++;
        coinText.text = "Coins: " + coinCount;

        Destroy(coin);

        if (coinCount % coinsForHealth == 0)
        {
            health++;
            UpdateHealthUI();

            coinCount -= coinsForHealth;
            coinText.text = "Coins: " + coinCount;
        }
    }

    void TakeDamage()
    {
        if (isGameOver) return;

        if (Time.time - lastHitTime < damageCooldown)
            return;

        lastHitTime = Time.time;

        health--;

        audioSource.PlayOneShot(hitSound);

        UpdateHealthUI();

        if (health <= 0)
        {
            GameOver();
        }
    }

    void UpdateHealthUI()
    {
        if (healthText != null)
            healthText.text = "Health: " + health;
    }

    void GameOver()
    {
        isGameOver = true;

        if (gameOverPanel != null)
            gameOverPanel.SetActive(true);

        Time.timeScale = 0f;
    }

    public void RestartGame()
    {
        Time.timeScale = 1f;
        SceneManager.LoadScene(SceneManager.GetActiveScene().buildIndex);
    }
}