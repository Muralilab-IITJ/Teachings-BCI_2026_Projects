using UnityEngine;
using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

public class BlinkReceiver : MonoBehaviour
{
    public int port = 5055;
    private UdpClient client;
    private Thread receiveThread;

    private volatile bool running = true;

    private bool jumpFlag = false;
    private bool leftFlag = false;
    private bool rightFlag = false;

    public PlayerController3D playerController;

    void Start()
    {
        try
        {
            client = new UdpClient(port);
            receiveThread = new Thread(ReceiveData);
            receiveThread.IsBackground = true;
            receiveThread.Start();

            Debug.Log("UDP Receiver started on port: " + port);
        }
        catch (Exception e)
        {
            Debug.LogError("UDP Start Error: " + e.Message);
        }
    }

    void ReceiveData()
    {
        IPEndPoint anyIP = new IPEndPoint(IPAddress.Any, port);

        while (running)
        {
            try
            {
                byte[] data = client.Receive(ref anyIP);
                string message = Encoding.UTF8.GetString(data).Trim().ToLower();

                Debug.Log("Received: " + message);

                if (message == "jump")
                {
                    Debug.Log("Jump command received");
                    jumpFlag = true;
                }

                else if (message == "left") 
                {
                    Debug.Log("left command received");
                    leftFlag = true; 
                }

                else if (message == "right")
                {
                    Debug.Log("left command received"); 
                    rightFlag = true;
                }
            }
            catch (SocketException)
            {
                // Happens when closing → safe ignore
            }
            catch (Exception e)
            {
                Debug.LogError("UDP Receive Error: " + e.Message);
            }
        }
    }

    void Update()
    {
        if (playerController == null) return;

        if (jumpFlag)
        {
            playerController.Jump();
            jumpFlag = false;
        }

        if (leftFlag)
        {
            playerController.ExternalTurn(-90f);
            leftFlag = false;
        }

        if (rightFlag)
        {
            playerController.ExternalTurn(90f);
            rightFlag = false;
        }
    }

    void OnApplicationQuit()
    {
        running = false;

        if (receiveThread != null && receiveThread.IsAlive)
        {
            receiveThread.Join();
        }

        if (client != null)
        {
            client.Close();
        }

        Debug.Log("UDP Receiver stopped.");
    }
}