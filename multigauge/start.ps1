$ErrorActionPreference='Stop'
$mgRoot=$PSScriptRoot
$repoRoot=Split-Path -Parent $mgRoot
$stamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$logDir=Join-Path $mgRoot 'evidence'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $mgRoot 'results') -Force | Out-Null
$containerNames=@(docker container ls -a --format '{{.Names}}')
if('physicalai-multigauge' -in $containerNames){
    $existing=docker inspect physicalai-multigauge
    $container=($existing|ConvertFrom-Json)[0]
    if($container.Config.Labels.'com.docker.compose.project' -ne 'physicalai-multigauge'){throw 'Existing container has a different Compose owner.'}
    if($container.Image -ne 'sha256:b58ec74c019aacd9ce4818fa25fc5a9e0a1f22f8c9cd1f5260994bf15cd9eb63'){throw 'Existing container has a different image.'}
    $bindings=@($container.HostConfig.PortBindings.'80/tcp')
    if($bindings.Count -ne 1 -or $bindings[0].HostIp -ne '127.0.0.1' -or $bindings[0].HostPort -ne '6084'){throw 'Existing container has unexpected VNC port binding.'}
    $expected=@{'/home/ubuntu/multigauge'=$mgRoot;'/home/ubuntu/camera_demo'=(Join-Path $repoRoot 'camera_demo');'/home/ubuntu/final_project'=(Join-Path $repoRoot 'final_project');'/home/ubuntu/final_ws'=(Join-Path $repoRoot 'final_project\ros2_ws')}
    foreach($dest in $expected.Keys){
        $mount=@($container.Mounts|Where-Object Destination -eq $dest)
        if($mount.Count -ne 1 -or [IO.Path]::GetFullPath($mount[0].Source).TrimEnd('\') -ne [IO.Path]::GetFullPath($expected[$dest]).TrimEnd('\')){throw "Unexpected bind mount for $dest"}
    }
    foreach($value in @('ROS_DOMAIN_ID=46','IGN_PARTITION=physicalai_multigauge_46','GZ_PARTITION=physicalai_multigauge_46')){if($value -notin $container.Config.Env){throw "Unexpected environment: $value"}}
}
$world=Join-Path $mgRoot 'generated\world.sdf'
if(-not(Test-Path -LiteralPath $world)){
    New-Item -ItemType Directory -Path (Split-Path -Parent $world) -Force | Out-Null
    $text=[IO.File]::ReadAllText((Join-Path $repoRoot 'camera_demo\worlds\camera_table.sdf')).Replace('world name="camera_demo"','world name="multigauge_demo"')
    [IO.File]::WriteAllText($world,$text,[Text.UTF8Encoding]::new($false))
}
docker compose -f (Join-Path $mgRoot 'compose.yaml') up -d
if($LASTEXITCODE -ne 0){throw 'Compose startup failed.'}
docker exec physicalai-multigauge test -f /home/ubuntu/camera_demo/ros2_ws/install/setup.bash
$cameraBuilt=$LASTEXITCODE -eq 0
docker exec physicalai-multigauge test -f /home/ubuntu/final_ws/install/setup.bash
$finalBuilt=$LASTEXITCODE -eq 0
if(-not($cameraBuilt -and $finalBuilt)){
    docker exec physicalai-multigauge bash /home/ubuntu/camera_demo/scripts/build_ros.sh 2>&1 | Tee-Object -FilePath (Join-Path $logDir "build_$stamp.log")
    if($LASTEXITCODE -ne 0){throw 'ROS build failed.'}
}
docker exec physicalai-multigauge python3 /home/ubuntu/multigauge/ready.py --process-check
$processCode=$LASTEXITCODE
if($processCode -eq 3){
    $displayReady=$false
    for($i=0;$i -lt 30;$i++){
        $savedPreference=$ErrorActionPreference
        $ErrorActionPreference='Continue'
        docker exec -e DISPLAY=:0 -e XAUTHORITY=/home/ubuntu/.Xauthority physicalai-multigauge xdpyinfo > $null 2>$null
        $displayCode=$LASTEXITCODE
        $ErrorActionPreference=$savedPreference
        if($displayCode -eq 0){$displayReady=$true;break}
        Start-Sleep -Milliseconds 500
    }
    if(-not $displayReady){throw 'X11 display not ready; simulator not launched.'}
    docker exec -u ubuntu physicalai-multigauge python3 /home/ubuntu/multigauge/desktop_guard.py
    if($LASTEXITCODE -ne 0){throw 'Desktop idle-overlay guard failed.'}
    $launchCommand="exec bash /home/ubuntu/multigauge/start_simulator.sh > /home/ubuntu/multigauge/evidence/simulator_$stamp.log 2>&1"
    docker exec -d physicalai-multigauge bash -c $launchCommand
    if($LASTEXITCODE -ne 0){throw 'Simulator launch failed.'}
}elseif($processCode -ne 0){throw 'More than one simulator launcher or process check failed.'}
$readyCommand="source /opt/ros/humble/setup.bash && python3 /home/ubuntu/multigauge/ready.py --report /home/ubuntu/multigauge/evidence/ready_$stamp.json"
docker exec physicalai-multigauge bash -c $readyCommand
if($LASTEXITCODE -ne 0){throw 'ROS/Gazebo readiness failed; see evidence logs.'}
Write-Output 'Ready: http://localhost:6084/ (isolated multigauge environment)'