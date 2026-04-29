using System.Collections.Generic;
using UnityEngine;

public class TileManager : MonoBehaviour
{
    public GameObject[] tilePrefabs; // 0 = Straight, 1 = Left, 2 = Right
    public Transform player;

    public int tilesOnScreen = 10;
    public int safeStartTiles = 5;

    private int tilesSpawned = 0;

    private List<GameObject> activeTiles = new List<GameObject>();
    private Transform lastSpawnPoint;

    // 🔥 NEW: OBSTACLE SETTINGS
    public GameObject obstaclePrefab;
    public int obstaclesPerTile = 3;

    public GameObject coinPrefab;
    public int coinsPerTile = 3;

    void Start()
    {
        GameObject firstTile = Instantiate(tilePrefabs[0], Vector3.zero, Quaternion.identity);

        lastSpawnPoint = firstTile.transform.Find("SpawnPoint");
        activeTiles.Add(firstTile);

        tilesSpawned = 1;

        for (int i = 0; i < tilesOnScreen; i++)
        {
            SpawnTile();
        }
    }

    void Update()
    {
        if (Vector3.Distance(player.position, lastSpawnPoint.position) < 80f)
        {
            SpawnTile();
            DeleteTile();
        }
    }

    void SpawnCoins(GameObject tile)
    {
        Transform ground = tile.transform.Find("GroundTile");
        if (ground == null) return;

        float tileLength = 20f;
        float tileWidth = 6f;

        int count = Random.Range(1, coinsPerTile + 1);

        for (int i = 0; i < count; i++)
        {
            float randomZ = Random.Range(2f, tileLength - 2f);
            float randomX = Random.Range(-tileWidth / 2f + 1f, tileWidth / 2f - 1f);

            Vector3 localPos = new Vector3(randomX, 1f, randomZ);
            Vector3 worldPos = tile.transform.TransformPoint(localPos);

            Instantiate(coinPrefab, worldPos, Quaternion.identity, tile.transform);
        }
    }
    void SpawnTile()
    {
        GameObject prefab;

        if (tilesSpawned < safeStartTiles)
        {
            prefab = tilePrefabs[0];
        }
        else
        {
            int index = Random.Range(0, tilePrefabs.Length);
            prefab = tilePrefabs[index];
        }

        Quaternion newRotation = lastSpawnPoint.rotation * prefab.transform.rotation;

        GameObject newTile = Instantiate(prefab, lastSpawnPoint.position, newRotation);

        // 🔥 SPAWN OBSTACLES ON THIS TILE
        SpawnObstacles(newTile);
        SpawnCoins(newTile);

        lastSpawnPoint = newTile.transform.Find("SpawnPoint");
        activeTiles.Add(newTile);

        tilesSpawned++;
    }

    // -----------------------------
    // 🔥 OBSTACLE SPAWNING LOGIC
    // -----------------------------
    void SpawnObstacles(GameObject tile)
    {
        // 🔥 Don't spawn in starting safe tiles
        if (tilesSpawned < safeStartTiles) return;

        // 🔥 50% chance to spawn obstacles
        float spawnChance = 0.5f;

        if (Random.value > spawnChance)
            return; // skip this tile (empty tile)

        Transform ground = tile.transform.Find("GroundTile");
        if (ground == null) return;

        float tileLength = 20f;
        float tileWidth = 6f;

        // 🔥 Random number of obstacles (1 to max)
        int count = Random.Range(1, obstaclesPerTile + 1);

        for (int i = 0; i < count; i++)
        {
            float randomZ = Random.Range(4f, tileLength - 2f);
            float randomX = Random.Range(-tileWidth / 2f + 1f, tileWidth / 2f - 1f);

            Vector3 localPos = new Vector3(randomX, 1f, randomZ);
            Vector3 worldPos = tile.transform.TransformPoint(localPos);

            Instantiate(obstaclePrefab, worldPos, tile.transform.rotation, tile.transform);
        }
    }

    void DeleteTile()
    {
        if (activeTiles.Count > tilesOnScreen)
        {
            Destroy(activeTiles[0]);
            activeTiles.RemoveAt(0);
        }
    }
}