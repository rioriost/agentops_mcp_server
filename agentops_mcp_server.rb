class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/bc/a4/b984bc82ccd93d2dff28cb10d79f2108d3f28a27bfc258067c7b74089a69/agentops_mcp_server-0.4.4.tar.gz"
  sha256 "c9331674607174d3e474c7effaed77079dab5c4b237ebd5a333e9ab63ae683f5"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
